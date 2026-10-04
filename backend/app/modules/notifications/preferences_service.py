# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""A member's own notification preferences (§B6.3 rule 7, M1.5-T7).

Default is on for every cell; only a stored `enabled = false` switches one off. In-app stays on for an
event whose notice an automation rule marks mandatory. A member reads and changes only their own
matrix; every change is audited with its outbox row in the same transaction.
"""

from __future__ import annotations

import json
from uuid import UUID

from app.core import clock
from app.core.db import Connection
from app.core.ids import uuid7
from app.core.problems import FieldError, ValidationFailedError
from app.engines.automation.subscriber import mandatory_inapp_events
from app.modules.audit.service import record_audit_event
from app.modules.event_registry import default_event_registry
from app.modules.notifications.errors import PreferenceLockedError, PreferenceVersionConflictError
from app.modules.notifications.preference_schemas import (
    PreferenceCell,
    PreferenceChange,
    PreferenceEvent,
    PreferenceMatrix,
)

__all__ = ["get_matrix", "set_preferences"]

CHANGED = "notification_preferences.changed"


async def _channels(conn: Connection) -> list[str]:
    """`inapp` (always on offer) and every installed, enabled channel, in a stable order."""
    rows = await conn.fetch("SELECT channel_key FROM public.notification_channels WHERE enabled = true")
    return sorted({"inapp", *(r["channel_key"] for r in rows)})


async def _mandatory(conn: Connection) -> set[str]:
    domain_key = await conn.fetchval("SELECT domain_key FROM public.organizations")
    return mandatory_inapp_events(domain_key) if domain_key else set()


async def get_matrix(conn: Connection, *, member_id: UUID) -> PreferenceMatrix:
    """The caller's own matrix: every registered event type by every available channel."""
    channels = await _channels(conn)
    locked = await _mandatory(conn)
    stored = {
        (r["event_type"], r["channel_key"]): (r["enabled"], r["version"])
        for r in await conn.fetch(
            "SELECT event_type, channel_key, enabled, version FROM public.notification_preferences "
            "WHERE member_id = $1",
            member_id,
        )
    }
    events = [
        PreferenceEvent(
            event_type=event_type,
            channels=[
                PreferenceCell(
                    channel_key=channel,
                    enabled=stored.get((event_type, channel), (True, 0))[0],
                    version=stored.get((event_type, channel), (True, 0))[1],
                    locked=channel == "inapp" and event_type in locked,
                )
                for channel in channels
            ],
        )
        for event_type in sorted(default_event_registry().known_event_types())
    ]
    return PreferenceMatrix(channels=channels, events=events)


def _invalid(index: int, field: str, message: str) -> ValidationFailedError:
    return ValidationFailedError(errors=[FieldError(field=f"body.changes.{index}.{field}", message=message)])


async def set_preferences(
    conn: Connection,
    *,
    organization_id: UUID,
    member_id: UUID,
    changes: list[PreferenceChange],
    request_id: str | None = None,
) -> PreferenceMatrix:
    """Apply `changes` to the caller's own preferences, all or nothing."""
    channels = set(await _channels(conn))
    locked = await _mandatory(conn)
    known = set(default_event_registry().known_event_types())
    seen: set[tuple[str, str]] = set()
    for index, change in enumerate(changes):
        cell = (change.event_type, change.channel_key)
        if change.event_type not in known:
            raise _invalid(index, "event_type", "Unknown event type.")
        if change.channel_key not in channels:
            raise _invalid(index, "channel_key", "This channel is not available.")
        if cell in seen:
            raise _invalid(index, "event_type", "Each event type and channel may appear once.")
        seen.add(cell)
        if not change.enabled and change.channel_key == "inapp" and change.event_type in locked:
            raise PreferenceLockedError()

    applied: list[dict[str, object]] = []
    now = clock.now()
    for change in changes:
        row = await conn.fetchrow(
            "SELECT id, enabled, version FROM public.notification_preferences "
            "WHERE member_id = $1 AND event_type = $2 AND channel_key = $3 FOR UPDATE",
            member_id,
            change.event_type,
            change.channel_key,
        )
        current_version = row["version"] if row is not None else 0
        if (change.version or 0) != current_version:
            raise PreferenceVersionConflictError()
        if row is None:
            if change.enabled:
                continue  # never stored and on: it is already the default
            await conn.execute(
                "INSERT INTO public.notification_preferences "
                "(id, organization_id, member_id, event_type, channel_key, enabled) "
                "VALUES ($1, $2, $3, $4, $5, false)",
                uuid7(),
                organization_id,
                member_id,
                change.event_type,
                change.channel_key,
            )
        elif row["enabled"] == change.enabled:
            continue
        else:
            await conn.execute(
                "UPDATE public.notification_preferences SET enabled = $2, version = version + 1, "
                "updated_at = $3 WHERE id = $1",
                row["id"],
                change.enabled,
                now,
            )
        applied.append(
            {"event_type": change.event_type, "channel_key": change.channel_key, "enabled": change.enabled}
        )

    if applied:
        after = {"member_id": str(member_id), "changes": applied}
        await record_audit_event(
            conn,
            organization_id=organization_id,
            actor_member_id=member_id,
            action=CHANGED,
            entity_type="member",
            entity_id=member_id,
            request_id=request_id,
            after_state=after,
        )
        await conn.execute(
            "INSERT INTO public.outbox "
            "(id, organization_id, event_type, aggregate_type, aggregate_id, payload) "
            "VALUES ($1, $2, $3, 'member', $4, $5::jsonb)",
            uuid7(),
            organization_id,
            CHANGED,
            member_id,
            json.dumps(after),
        )
    return await get_matrix(conn, member_id=member_id)
