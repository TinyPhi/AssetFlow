# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Outbox dispatcher: claim, run subscribers, record the result (§B9.3, §B6.2, §B10).

Three short steps per batch, none of which holds a transaction across another:
  1. claim: one transaction marks rows with `FOR UPDATE SKIP LOCKED` and commits;
  2. run: each subscriber works in its own transaction under the event's organization;
  3. record: one transaction per row stores success, failure or dead letter.

A worker that dies between steps 2 and 3 leaves a claim that expires after
`reclaim_after_seconds`; the row is claimed again and `processed_events` makes the repeat a no-op.
"""

from __future__ import annotations

import contextlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.core.db import Pool, worker_claim_transaction, worker_context
from app.core.ids import uuid7
from app.providers.telemetry.base import TelemetryProvider
from workers.subscribers import OutboxEvent, SubscriberRegistry

logger = logging.getLogger(__name__)

SPAN_NAME = "worker.outbox_dispatcher.run"
LAG_METRIC = "assetflow_outbox_lag_seconds"
DEAD_LETTER_METRIC = "assetflow_outbox_dead_lettered_total"


@dataclass(frozen=True)
class DispatcherOptions:
    """The `workers.outbox` settings the dispatcher needs."""

    batch_size: int = 50
    reclaim_after_seconds: int = 300
    max_attempts: int = 5


_CLAIM_SQL = """
UPDATE public.outbox AS o
SET claimed_at = now(), claimed_by = $1, attempts = o.attempts + 1
WHERE o.id IN (
    SELECT p.id FROM public.outbox AS p
    WHERE p.processed_at IS NULL AND p.dead_lettered_at IS NULL
      AND (p.claimed_at IS NULL OR p.claimed_at < now() - make_interval(secs => $3))
    ORDER BY p.created_at
    LIMIT $2
    FOR UPDATE SKIP LOCKED
)
RETURNING o.id, o.organization_id, o.event_type, o.aggregate_type, o.aggregate_id, o.payload,
          o.attempts, o.created_at AS occurred_at,
          EXTRACT(EPOCH FROM now() - o.created_at)::float8 AS lag_seconds
"""

_DEAD_LETTER_EXPIRED_SQL = """
UPDATE public.outbox
SET dead_lettered_at = now(), claimed_at = NULL, claimed_by = NULL, last_error = 'ClaimExpired'
WHERE processed_at IS NULL AND dead_lettered_at IS NULL AND attempts >= $1
  AND claimed_at IS NOT NULL AND claimed_at < now() - make_interval(secs => $2)
RETURNING organization_id, event_type
"""


def _event(row: Any) -> OutboxEvent:
    payload = row["payload"]
    return OutboxEvent(
        id=row["id"],
        organization_id=row["organization_id"],
        event_type=row["event_type"],
        aggregate_type=row["aggregate_type"],
        aggregate_id=row["aggregate_id"],
        payload=json.loads(payload) if isinstance(payload, str) else dict(payload),
        attempts=row["attempts"],
        occurred_at=row["occurred_at"],
    )


def _log(message: str, organization_id: object, event_type: str, error_code: str, *, error: bool) -> None:
    fields = {"organization_id": str(organization_id), "event_type": event_type, "error_code": error_code}
    (logger.error if error else logger.warning)(message, extra=fields)


async def claim_batch(
    pool: Pool, worker_id: str, options: DispatcherOptions
) -> tuple[list[OutboxEvent], float]:
    """Claim up to `batch_size` rows; return them and the oldest one's age in seconds.

    Rows whose claim expired after `max_attempts` claims are dead-lettered instead of claimed again,
    so an event that kills the worker every time cannot loop forever.
    """
    async with worker_claim_transaction(pool) as conn:
        expired = await conn.fetch(
            _DEAD_LETTER_EXPIRED_SQL, options.max_attempts, float(options.reclaim_after_seconds)
        )
        rows = await conn.fetch(
            _CLAIM_SQL, worker_id, options.batch_size, float(options.reclaim_after_seconds)
        )
    for row in expired:
        _log("outbox.dead_lettered", row["organization_id"], row["event_type"], "ClaimExpired", error=True)
    lag = max((float(row["lag_seconds"]) for row in rows), default=0.0)
    return [_event(row) for row in rows], lag


async def run_subscribers(pool: Pool, registry: SubscriberRegistry, event: OutboxEvent) -> None:
    """Run every subscriber of `event`, each once per event (idempotent consumer, §B6.2)."""
    for subscription in registry.for_event(event.event_type):
        async with worker_context(pool, event.organization_id) as conn:
            inserted = await conn.fetchval(
                "INSERT INTO public.processed_events (id, organization_id, consumer_name, event_id) "
                "VALUES ($1, $2, $3, $4) "
                "ON CONFLICT (organization_id, consumer_name, event_id) DO NOTHING RETURNING id",
                uuid7(),
                event.organization_id,
                subscription.consumer,
                event.id,
            )
            if inserted is not None:
                await subscription.handler(conn, event)


async def record_success(pool: Pool, worker_id: str, event: OutboxEvent) -> bool:
    """Mark the row processed and clear the claim; False when the claim was lost meanwhile."""
    async with worker_claim_transaction(pool) as conn:
        done = await conn.fetchval(
            "UPDATE public.outbox SET processed_at = now(), claimed_at = NULL, claimed_by = NULL, "
            "last_error = NULL WHERE id = $1 AND claimed_by = $2 AND processed_at IS NULL RETURNING id",
            event.id,
            worker_id,
        )
    return done is not None


async def record_failure(
    pool: Pool, worker_id: str, event: OutboxEvent, error_code: str, max_attempts: int
) -> bool:
    """Store the error class and clear the claim; dead-letter at `max_attempts`.

    Returns True when the row was dead-lettered.
    """
    async with worker_claim_transaction(pool) as conn:
        dead = await conn.fetchval(
            "UPDATE public.outbox SET last_error = $3, claimed_at = NULL, claimed_by = NULL, "
            "dead_lettered_at = CASE WHEN attempts >= $4 THEN now() END "
            "WHERE id = $1 AND claimed_by = $2 AND processed_at IS NULL "
            "RETURNING (dead_lettered_at IS NOT NULL)",
            event.id,
            worker_id,
            error_code,
            max_attempts,
        )
    if dead:
        _log("outbox.dead_lettered", event.organization_id, event.event_type, error_code, error=True)
    return bool(dead)


async def release_claims(pool: Pool, worker_id: str, events: list[OutboxEvent]) -> None:
    """Give unhandled rows back (shutdown); the claim does not count as an attempt."""
    if not events:
        return
    async with worker_claim_transaction(pool) as conn:
        await conn.execute(
            "UPDATE public.outbox SET claimed_at = NULL, claimed_by = NULL, attempts = attempts - 1 "
            "WHERE id = ANY($1::uuid[]) AND claimed_by = $2 AND processed_at IS NULL",
            [event.id for event in events],
            worker_id,
        )


async def process_event(
    pool: Pool, registry: SubscriberRegistry, worker_id: str, event: OutboxEvent, options: DispatcherOptions
) -> bool:
    """Run one claimed event and record the outcome; return True when it was dead-lettered."""
    try:
        await run_subscribers(pool, registry, event)
    except Exception as exc:  # noqa: BLE001 - any subscriber failure is recorded by class and retried
        # A ProblemError (e.g. a job's time or memory limit) reports its formal code; anything
        # else reports its exception class name, as before.
        error_code = getattr(exc, "code", None) or type(exc).__name__
        _log("outbox.event_failed", event.organization_id, event.event_type, error_code, error=False)
        return await record_failure(pool, worker_id, event, error_code, options.max_attempts)
    await record_success(pool, worker_id, event)
    return False


async def run_once(
    pool: Pool,
    registry: SubscriberRegistry,
    worker_id: str,
    options: DispatcherOptions,
    *,
    telemetry: TelemetryProvider | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> int:
    """Claim and handle one batch; return the number of rows handled.

    When `should_stop()` turns true the rows not yet started are released and the batch ends after
    the row in progress.
    """
    span = telemetry.start_span(SPAN_NAME) if telemetry is not None else contextlib.nullcontext()
    with span:
        events, lag = await claim_batch(pool, worker_id, options)
        if telemetry is not None:
            telemetry.record_metric(LAG_METRIC, lag)
        handled = 0
        for index, event in enumerate(events):
            if should_stop is not None and should_stop():
                await release_claims(pool, worker_id, events[index:])
                break
            dead = await process_event(pool, registry, worker_id, event, options)
            if dead and telemetry is not None:
                telemetry.record_metric(DEAD_LETTER_METRIC, 1.0)
            handled += 1
        return handled
