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

from pathlib import Path
from uuid import UUID

from app.channels.base import ChannelContext, RenderedMessage
from app.channels.inapp import InAppChannel
from app.channels.templates import load_template_set
from app.core.db import Connection
from app.core.ids import uuid7
from app.engines.automation.planner import NotificationIntent

__all__ = ["TEMPLATES_DIR", "enqueue"]

#: `config/templates/en/` relative to the repository root (this file: backend/app/modules/notifications/).
TEMPLATES_DIR = Path(__file__).resolve().parents[4] / "config" / "templates" / "en"


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
    template = load_template_set(TEMPLATES_DIR, intent.template_key)
    message = RenderedMessage(
        subject=template.render("txt", intent.event_data) if "txt" in template.formats() else "",
        body=template.render("html", intent.event_data) if "html" in template.formats() else "",
        data={
            "event_type": intent.event_type,
            "event_id": str(intent.event_id),
            "template_key": intent.template_key,
        },
    )
    ctx = ChannelContext(organization_id=str(intent.organization_id), installation={})
    channel = InAppChannel(conn)
    result = await channel.send(ctx, str(intent.member_id), message, intent.idempotency_key)
    await conn.execute(
        "INSERT INTO public.notification_deliveries "
        "(id, organization_id, channel_id, channel_key, event_id, recipient_member_id, target, "
        "idempotency_key, status) "
        "VALUES ($1, $2, $3, 'inapp', $4, $5, $6, $7, $8) "
        "ON CONFLICT (organization_id, idempotency_key) DO NOTHING",
        uuid7(),
        intent.organization_id,
        channel_id,
        intent.event_id,
        intent.member_id,
        str(intent.member_id),
        intent.idempotency_key,
        "sent" if result.delivered else "skipped",
    )


async def _record_pending(conn: Connection, intent: NotificationIntent) -> None:
    await conn.execute(
        "INSERT INTO public.notification_deliveries "
        "(id, organization_id, channel_id, channel_key, event_id, recipient_member_id, target, "
        "idempotency_key, status) "
        "SELECT $1, $2, nc.id, $3, $4, $5, $6, $7, 'pending' "
        "FROM public.notification_channels nc WHERE nc.organization_id = $2 AND nc.channel_key = $3 "
        "ON CONFLICT (organization_id, idempotency_key) DO NOTHING",
        uuid7(),
        intent.organization_id,
        intent.channel_key,
        intent.event_id,
        intent.member_id,
        str(intent.member_id),
        intent.idempotency_key,
    )
