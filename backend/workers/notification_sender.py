# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The notification sender: pending deliveries out through their channel (§B6.3, §B9.3, M1.5-T6).

Per active organization, three separate steps, never one transaction across a send (§B10):

1. claim: in one short transaction, return stale `sending` claims to `failed`, dead-letter any
   delivery whose attempts ran out while its worker died, and move due `pending` / `failed` rows to
   `sending` (counting the attempt) with `FOR UPDATE SKIP LOCKED`, so two senders never take the same
   row;
2. send: outside any transaction, check the kill switch and the circuit breaker, build the channel
   context, render and call `channel.send`;
3. record: in a second short transaction, write the outcome. A delivery that has used its 3rd
   attempt, or failed in a way retrying cannot fix, is dead-lettered in that same transaction with
   its effects: an in-app alert to every organization admin, an audit event on the related record
   (the note, §B6.3 rule 5) and an outbox row.

A delivery already `sent` is never claimed again (§B6.3 rule 8). The one resend case is a worker
that dies after `send` returned but before step 3: its claim goes stale, returns to `failed`, and
the delivery is sent once more.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from app.channels.base import DeliveryResult
from app.channels.circuit import CircuitRegistry
from app.channels.registry import ChannelRegistry
from app.channels.retry import MAX_ATTEMPTS, backoff_seconds, failure_from_exception
from app.channels.runtime import ChannelRuntime
from app.channels.templates import TemplateError
from app.core import clock
from app.core.db import Connection, Pool, worker_context
from app.core.ids import uuid7
from app.core.permissions import ScopeType
from app.engines.automation.directory_pg import PgDirectory
from app.engines.automation.planner import NotificationIntent
from app.modules.audit.service import record_audit_event
from app.modules.notifications.dispatch import enqueue
from app.modules.notifications.rendering import render_message
from app.providers.telemetry.base import TelemetryProvider
from workers.sweep import active_organization_ids

logger = logging.getLogger(__name__)

__all__ = ["SPAN_NAME", "SenderDeps", "SenderOptions", "run_once"]

SPAN_NAME = "worker.notification_sender.run"
SENT_METRIC = "assetflow_notifications_sent_total"
FAILED_METRIC = "assetflow_notifications_failed_total"
DEAD_LETTERED_METRIC = "assetflow_notifications_dead_lettered_total"
DEAD_LETTER_TEMPLATE = "delivery-dead-lettered"
DEAD_LETTER_EVENT = "notification_delivery.dead_lettered"

_RELEASE_STALE_SQL = (
    "UPDATE public.notification_deliveries "
    "SET status = 'failed', claimed_by = NULL, claimed_at = NULL, next_retry_at = $1, updated_at = $1 "
    "WHERE status = 'sending' AND claimed_at < $2"
)
_EXHAUSTED_SQL = (
    "SELECT id, channel_id, channel_key, event_id, recipient_member_id, target, idempotency_key, attempts, "
    "template_key, event_type, entity_type, entity_id, message_data "
    "FROM public.notification_deliveries "
    "WHERE status = 'failed' AND attempts >= $1 FOR UPDATE SKIP LOCKED"
)
_CLAIM_SQL = (
    "UPDATE public.notification_deliveries "
    "SET status = 'sending', attempts = attempts + 1, claimed_by = $1, claimed_at = $2, updated_at = $2 "
    "WHERE id IN ("
    "SELECT id FROM public.notification_deliveries "
    "WHERE status IN ('pending', 'failed') AND attempts < $3 "
    "AND (next_retry_at IS NULL OR next_retry_at <= $2) "
    "ORDER BY created_at, id LIMIT $4 FOR UPDATE SKIP LOCKED) "
    "RETURNING id, channel_id, channel_key, event_id, recipient_member_id, target, idempotency_key, "
    "attempts, template_key, event_type, entity_type, entity_id, message_data"
)


@dataclass(frozen=True)
class SenderOptions:
    """Tunables of one sender pass."""

    batch_size: int = 20
    stale_after_seconds: int = 300
    admin_role: str = "admin"


@dataclass
class SenderDeps:
    """What the sender needs besides the database."""

    channels: ChannelRegistry
    runtime: ChannelRuntime
    breakers: CircuitRegistry
    telemetry: TelemetryProvider | None = None


@dataclass(frozen=True)
class _Pass:
    """One organization's pass: everything the steps share."""

    pool: Pool
    deps: SenderDeps
    opts: SenderOptions
    worker: str
    organization_id: UUID


@dataclass(frozen=True)
class _Delivery:
    id: UUID
    channel_id: UUID
    channel_key: str
    event_id: UUID
    recipient_member_id: UUID | None
    target: str
    idempotency_key: str
    attempts: int
    template_key: str | None
    event_type: str | None
    entity_type: str | None
    entity_id: UUID | None
    message_data: dict[str, Any]


def _delivery(row: Any) -> _Delivery:
    data = row["message_data"]
    return _Delivery(
        id=row["id"],
        channel_id=row["channel_id"],
        channel_key=row["channel_key"],
        event_id=row["event_id"],
        recipient_member_id=row["recipient_member_id"],
        target=row["target"],
        idempotency_key=row["idempotency_key"],
        attempts=row["attempts"],
        template_key=row["template_key"],
        event_type=row["event_type"],
        entity_type=row["entity_type"],
        entity_id=row["entity_id"],
        message_data=json.loads(data) if isinstance(data, str) else dict(data or {}),
    )


async def run_once(pool: Pool, deps: SenderDeps, worker: str, options: SenderOptions | None = None) -> int:
    """One pass over every active organization; returns how many deliveries were attempted."""
    opts = options or SenderOptions()
    span = deps.telemetry.start_span(SPAN_NAME) if deps.telemetry is not None else contextlib.nullcontext()
    attempted = 0
    with span:
        for organization_id in await active_organization_ids(pool):
            try:
                attempted += await _process(_Pass(pool, deps, opts, worker, organization_id))
            except Exception as exc:  # noqa: BLE001 - one organization's failure must not stop the pass
                logger.warning(
                    "worker.notification_sender.failed",
                    extra={"organization_id": str(organization_id), "error_code": type(exc).__name__},
                )
    return attempted


async def _process(p: _Pass) -> int:
    claimed = await _claim(p)
    for delivery in claimed:
        await _deliver(p, delivery)
    return len(claimed)


# ------------------------------------------------------------------------------------------ claim


async def _claim(p: _Pass) -> list[_Delivery]:
    now = clock.now()
    async with worker_context(p.pool, p.organization_id) as conn:
        await conn.execute(_RELEASE_STALE_SQL, now, now - timedelta(seconds=p.opts.stale_after_seconds))
        for row in await conn.fetch(_EXHAUSTED_SQL, MAX_ATTEMPTS):
            await _dead_letter(p, conn, _delivery(row), "worker_interrupted", now=now)
        rows = await conn.fetch(_CLAIM_SQL, p.worker, now, MAX_ATTEMPTS, p.opts.batch_size)
    return [_delivery(r) for r in rows]


# ----------------------------------------------------------------------------------------- deliver


async def _deliver(p: _Pass, d: _Delivery) -> None:
    async with worker_context(p.pool, p.organization_id) as conn:
        installation = await conn.fetchrow(
            "SELECT id, channel_key, settings, secret_ref, enabled, allowed_hosts "
            "FROM public.notification_channels WHERE id = $1",
            d.channel_id,
        )
    if installation is None or not installation["enabled"]:
        await _skip(p, d, "channel.disabled")  # the kill switch (§B6.3 rule 6)
        return
    channel_class = p.deps.channels.get(d.channel_key)
    if channel_class is None or d.template_key is None:
        await _skip(p, d, "channel.unknown")
        return

    breaker = p.deps.breakers.get(p.organization_id, d.channel_id)
    if not breaker.allow(clock.now()):
        await _hold(p, d, breaker.retry_after(clock.now()))
        return

    try:
        message = render_message(d.template_key, d.event_type or "", d.event_id, d.message_data)
    except TemplateError:
        breaker.release_trial()
        await _record(p, d, DeliveryResult(delivered=False, error_code="template.invalid", retryable=False))
        return
    started = time.monotonic()
    try:
        channel = channel_class()
        ctx = await p.deps.runtime.build_context(channel, str(p.organization_id), dict(installation))
        result = await channel.send(ctx, d.target, message, d.idempotency_key)
    except Exception as exc:  # noqa: BLE001 - a channel must not take the sender down
        result = failure_from_exception(exc)
    if result.latency_ms is None:
        result = DeliveryResult(
            result.delivered, result.error_code, int((time.monotonic() - started) * 1000), result.retryable
        )

    if result.delivered:
        breaker.record_success()
    elif result.retryable:
        breaker.record_failure(clock.now())
    else:
        breaker.release_trial()
    await _record(p, d, result)


# ----------------------------------------------------------------------------------------- record


def _count(p: _Pass, metric: str, d: _Delivery) -> None:
    if p.deps.telemetry is not None:
        p.deps.telemetry.record_metric(metric, 1.0, {"channel_key": d.channel_key})


async def _record(p: _Pass, d: _Delivery, result: DeliveryResult) -> None:
    now = clock.now()
    async with worker_context(p.pool, p.organization_id) as conn:
        if result.delivered:
            recorded = await conn.fetchval(
                "UPDATE public.notification_deliveries SET status = 'sent', latency_ms = $3, "
                "error_code = NULL, next_retry_at = NULL, claimed_by = NULL, claimed_at = NULL, "
                "updated_at = $4 "
                "WHERE id = $1 AND status = 'sending' AND claimed_by = $2 RETURNING id",
                d.id,
                p.worker,
                result.latency_ms,
                now,
            )
            if recorded is not None:
                _count(p, SENT_METRIC, d)
            return
        error_code = result.error_code or "unexpected_error"
        if result.retryable and d.attempts < MAX_ATTEMPTS:
            recorded = await conn.fetchval(
                "UPDATE public.notification_deliveries SET status = 'failed', latency_ms = $3, "
                "error_code = $4, next_retry_at = $5, claimed_by = NULL, claimed_at = NULL, "
                "updated_at = $6 "
                "WHERE id = $1 AND status = 'sending' AND claimed_by = $2 RETURNING id",
                d.id,
                p.worker,
                result.latency_ms,
                error_code,
                now + timedelta(seconds=backoff_seconds(d.attempts)),
                now,
            )
            if recorded is not None:
                _count(p, FAILED_METRIC, d)
            return
        await _dead_letter(p, conn, d, error_code, latency_ms=result.latency_ms, now=now, owned=True)


async def _skip(p: _Pass, d: _Delivery, error_code: str) -> None:
    """Record that nothing was sent (kill switch, unknown channel); the claim's attempt is given back."""
    async with worker_context(p.pool, p.organization_id) as conn:
        await conn.execute(
            "UPDATE public.notification_deliveries SET status = 'skipped', error_code = $3, "
            "attempts = GREATEST(attempts - 1, 0), claimed_by = NULL, claimed_at = NULL, "
            "next_retry_at = NULL, updated_at = $4 "
            "WHERE id = $1 AND status = 'sending' AND claimed_by = $2",
            d.id,
            p.worker,
            error_code,
            clock.now(),
        )


async def _hold(p: _Pass, d: _Delivery, retry_at: datetime) -> None:
    """The circuit is open: keep the delivery queued and do not count this attempt (§B6.1 rule 9)."""
    async with worker_context(p.pool, p.organization_id) as conn:
        await conn.execute(
            "UPDATE public.notification_deliveries "
            "SET status = CASE WHEN attempts > 1 THEN 'failed' ELSE 'pending' END, "
            "attempts = GREATEST(attempts - 1, 0), claimed_by = NULL, claimed_at = NULL, "
            "next_retry_at = $3, updated_at = $4 "
            "WHERE id = $1 AND status = 'sending' AND claimed_by = $2",
            d.id,
            p.worker,
            retry_at,
            clock.now(),
        )


# ------------------------------------------------------------------------------------ dead letter


async def _dead_letter(
    p: _Pass,
    conn: Connection,
    d: _Delivery,
    error_code: str,
    *,
    now: datetime,
    latency_ms: int | None = None,
    owned: bool = False,
) -> None:
    """Dead-letter `d` and, in the same transaction, tell the admins, note the record, queue the event.

    `owned` is True when this worker holds the delivery's `sending` claim (the post-send path); the
    claim step's own call already holds the row lock instead.
    """
    updated = await conn.fetchval(
        "UPDATE public.notification_deliveries SET status = 'dead_lettered', error_code = $3, "
        "latency_ms = COALESCE($4, latency_ms), next_retry_at = NULL, claimed_by = NULL, "
        "claimed_at = NULL, updated_at = $5 "
        "WHERE id = $1 AND (NOT $6 OR (status = 'sending' AND claimed_by = $2)) RETURNING id",
        d.id,
        p.worker,
        error_code,
        latency_ms,
        now,
        owned,
    )
    if updated is None:
        return
    admins = await PgDirectory(conn).members_with_role(p.opts.admin_role, ScopeType.ORGANIZATION, None)
    alerts = [
        NotificationIntent(
            event_id=d.event_id,
            organization_id=p.organization_id,
            member_id=admin,
            channel_key="inapp",
            template_key=DEAD_LETTER_TEMPLATE,
            idempotency_key=hashlib.sha256(f"{d.id}|{admin}|dead_lettered".encode()).hexdigest(),
            event_type=DEAD_LETTER_EVENT,
            event_data={"channel_key": d.channel_key, "error_code": error_code, "attempts": d.attempts},
        )
        for admin in sorted(admins)
    ]
    await enqueue(conn, alerts)
    summary = {
        "delivery_id": str(d.id),
        "channel_key": d.channel_key,
        "error_code": error_code,
        "attempts": d.attempts,
    }
    await record_audit_event(
        conn,
        organization_id=p.organization_id,
        action=DEAD_LETTER_EVENT,
        entity_type=d.entity_type or "notification_delivery",
        entity_id=d.entity_id or d.id,
        after_state=summary,
    )
    await conn.execute(
        "INSERT INTO public.outbox (id, organization_id, event_type, aggregate_type, aggregate_id, payload) "
        "VALUES ($1, $2, $3, 'notification_delivery', $4, $5::jsonb)",
        uuid7(),
        p.organization_id,
        DEAD_LETTER_EVENT,
        d.id,
        json.dumps(summary),
    )
    _count(p, DEAD_LETTERED_METRIC, d)
