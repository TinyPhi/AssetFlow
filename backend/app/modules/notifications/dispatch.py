# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Hand planned notification intents to the channels that send them (§B6.3, M1.5-T3).

`inapp` intents are sent directly, in the same transaction as everything else the subscriber does
(no external call, so nothing here needs a retry or a queue of its own). Every other channel is
only ever recorded as a `pending` delivery: P6-06b's sender is what actually calls out, later and
outside this transaction, since §B10 forbids an external call inside a request or subscriber
transaction.
"""

from __future__ import annotations

import json
import time
from functools import lru_cache
from typing import Any
from uuid import UUID

from app.channels.base import ChannelContext
from app.channels.inapp import InAppChannel
from app.channels.registry import ChannelRegistry, default_registry
from app.core.db import Connection
from app.core.ids import uuid7
from app.engines.automation.planner import NotificationIntent
from app.modules.event_registry import default_event_registry
from app.modules.notifications.rendering import TEMPLATES_DIR, minimized_data, render_message

__all__ = ["TEMPLATES_DIR", "enqueue"]


@lru_cache(maxsize=1)
def _channels() -> ChannelRegistry:
    return default_registry()


def _settings(value: Any) -> dict[str, Any]:
    return json.loads(value) if isinstance(value, str) else dict(value or {})


async def enqueue(conn: Connection, intents: list[NotificationIntent]) -> None:
    """Send every `inapp` intent now; record every other channel's intent as a pending delivery."""
    for intent in intents:
        if intent.channel_key == "inapp":
            await _send_inapp(conn, intent)
        else:
            await _record_pending(conn, intent)


async def _ensure_inapp_channel(conn: Connection, organization_id: UUID) -> UUID:
    """`inapp` needs no settings and no admin setup (§B6.3): install it on first use, idempotently."""
    channel_id = await conn.fetchval(
        "INSERT INTO public.notification_channels (id, organization_id, channel_key, display_name) "
        "VALUES ($1, $2, 'inapp', 'In-app') "
        "ON CONFLICT (organization_id, channel_key) DO NOTHING "
        "RETURNING id",
        uuid7(),
        organization_id,
    )
    if channel_id is not None:
        return UUID(str(channel_id))
    existing = await conn.fetchval(
        "SELECT id FROM public.notification_channels WHERE organization_id = $1 AND channel_key = 'inapp'",
        organization_id,
    )
    return UUID(str(existing))


async def _send_inapp(conn: Connection, intent: NotificationIntent) -> None:
    channel_id = await _ensure_inapp_channel(conn, intent.organization_id)
    message = render_message(intent.template_key, intent.event_type, intent.event_id, intent.event_data)
    ctx = ChannelContext(organization_id=str(intent.organization_id), installation={})
    channel = InAppChannel(conn)
    started = time.monotonic()
    result = await channel.send(ctx, str(intent.member_id), message, intent.idempotency_key)
    latency_ms = int((time.monotonic() - started) * 1000)
    await conn.execute(
        "INSERT INTO public.notification_deliveries "
        "(id, organization_id, channel_id, channel_key, event_id, recipient_member_id, target, "
        "idempotency_key, status, latency_ms) "
        "VALUES ($1, $2, $3, 'inapp', $4, $5, $6, $7, $8, $9) "
        "ON CONFLICT (organization_id, idempotency_key) DO NOTHING",
        uuid7(),
        intent.organization_id,
        channel_id,
        intent.event_id,
        intent.member_id,
        str(intent.member_id),
        intent.idempotency_key,
        "sent" if result.delivered else "skipped",
        latency_ms,
    )


async def _record_pending(conn: Connection, intent: NotificationIntent) -> None:
    """Queue an external delivery with everything the sender needs to render it later.

    Only the template's declared fields are stored (payload minimization), and its personal
    fields only when this installation allows personal data (§B6.3 rule 3). The sender renders and
    sends outside any transaction (§B10). A channel the organization has not installed delivers
    nothing, so nothing is recorded.
    """
    channel = await conn.fetchrow(
        "SELECT id, allow_personal_data, settings FROM public.notification_channels "
        "WHERE organization_id = $1 AND channel_key = $2",
        intent.organization_id,
        intent.channel_key,
    )
    if channel is None:
        return
    allow_personal = channel["allow_personal_data"]
    settings = _settings(channel["settings"])
    channel_class = _channels().get(intent.channel_key)
    custom: dict[str, Any] | None = None
    if channel_class is not None:
        installed = channel_class()
        if not installed.accepts_event(settings, intent.event_type):
            return
        spec = default_event_registry().get(intent.event_type)
        custom = installed.build_message_data(
            settings,
            intent.event_type,
            intent.event_data,
            intent.occurred_at,
            allow_personal=allow_personal,
            personal_fields=spec.personal_fields if spec is not None else frozenset(),
        )
    message_data = (
        custom
        if custom is not None
        else minimized_data(intent.template_key, intent.event_data, allow_personal=allow_personal)
    )
    await conn.execute(
        "INSERT INTO public.notification_deliveries "
        "(id, organization_id, channel_id, channel_key, event_id, recipient_member_id, target, "
        "idempotency_key, status, template_key, event_type, entity_type, entity_id, message_data) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'pending', $9, $10, $11, $12, $13::jsonb) "
        "ON CONFLICT (organization_id, idempotency_key) DO NOTHING",
        uuid7(),
        intent.organization_id,
        channel["id"],
        intent.channel_key,
        intent.event_id,
        intent.member_id,
        str(intent.member_id),
        intent.idempotency_key,
        intent.template_key,
        intent.event_type,
        intent.entity_type,
        intent.entity_id,
        json.dumps(message_data),
    )
