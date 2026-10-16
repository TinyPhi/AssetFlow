# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Inbox service: self-scoped reads, audited writes (§B10, §C4.5, §C5.4 rule 5, M1.5-T3).

Reading another member's notice never happens (every list and count query is filtered to the
caller's own `member_id` in `repository.py`); marking one as read is the one write this module has,
and a denied write answers 403 `scope.denied`, not 404 (§C4.5, §C5.4 rule 5 - a read outside scope
is 404, a write is 403; see this plan's Record for the master-plan citation other P5/P6 plans
needed the same correction for).
"""

from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

from app.core.db import Connection
from app.core.ids import uuid7
from app.core.problems import NotFoundError, PermissionDeniedError
from app.modules.audit.service import record_audit_event
from app.modules.notifications import repository

__all__ = ["decode_cursor", "list_inbox", "mark_all_read", "mark_read", "unread_count"]

#: The API layer parses a page cursor through the service, never the repository (§B4.2 rule 2).
decode_cursor = repository.decode_cursor

_READ_ACTION = "notification.read"
_READ_ALL_ACTION = "notification.read_all"


async def list_inbox(
    conn: Connection,
    *,
    member_id: UUID,
    unread_only: bool = False,
    updated_since: datetime | None = None,
    after: tuple[datetime, UUID] | None = None,
    limit: int = 20,
) -> tuple[list[dict[str, object]], str | None]:
    """The caller's own inbox page, and the cursor for the next page (None when this was the last)."""
    rows = await repository.list_notifications(
        conn,
        member_id=member_id,
        unread_only=unread_only,
        updated_since=updated_since,
        after=after,
        limit=limit,
    )
    next_cursor = None
    if len(rows) == limit:
        last = rows[-1]
        next_cursor = repository.encode_cursor(last["updated_at"], last["id"])
    return rows, next_cursor


async def unread_count(conn: Connection, *, member_id: UUID) -> int:
    """How many of the caller's own notices are unread."""
    return await repository.unread_count(conn, member_id=member_id)


async def mark_read(
    conn: Connection,
    *,
    organization_id: UUID,
    caller_member_id: UUID,
    notification_id: UUID,
    request_id: str | None = None,
) -> bool:
    """Mark one notice read; 404 if it does not exist, 403 if it is not the caller's own."""
    found = await repository.get_by_id(conn, notification_id=notification_id)
    if found is None:
        raise NotFoundError()
    if found["member_id"] != caller_member_id:
        raise PermissionDeniedError()
    changed = await repository.mark_read(conn, notification_id=notification_id)
    if changed:
        await record_audit_event(
            conn,
            organization_id=organization_id,
            actor_member_id=caller_member_id,
            action=_READ_ACTION,
            entity_type="notification",
            entity_id=notification_id,
            request_id=request_id,
        )
        payload: dict[str, object] = {"id": str(notification_id)}
        await _write_outbox(conn, organization_id, _READ_ACTION, notification_id, payload)
    return changed


async def mark_all_read(
    conn: Connection, *, organization_id: UUID, caller_member_id: UUID, request_id: str | None = None
) -> int:
    """Mark every one of the caller's own unread notices as read; returns how many changed."""
    count = await repository.mark_all_read(conn, member_id=caller_member_id)
    if count:
        await record_audit_event(
            conn,
            organization_id=organization_id,
            actor_member_id=caller_member_id,
            action=_READ_ALL_ACTION,
            entity_type="notification",
            entity_id=caller_member_id,
            request_id=request_id,
            after_state={"count": count},
        )
        await _write_outbox(conn, organization_id, _READ_ALL_ACTION, caller_member_id, {"count": count})
    return count


async def _write_outbox(
    conn: Connection, organization_id: UUID, event_type: str, aggregate_id: UUID, payload: dict[str, object]
) -> None:
    await conn.execute(
        "INSERT INTO public.outbox (id, organization_id, event_type, aggregate_type, aggregate_id, payload) "
        "VALUES ($1, $2, $3, 'notification', $4, $5::jsonb)",
        uuid7(),
        organization_id,
        event_type,
        aggregate_id,
        json.dumps(payload),
    )
