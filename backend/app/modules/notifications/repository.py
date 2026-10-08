# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The inbox repository: list, unread count, mark read (§B4.5 cursor pagination, M1.5-T3)."""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Any
from uuid import UUID

from app.core.db import Connection

__all__ = [
    "decode_cursor",
    "encode_cursor",
    "get_by_id",
    "list_notifications",
    "mark_all_read",
    "mark_read",
    "unread_count",
]


def encode_cursor(updated_at: datetime, notification_id: UUID) -> str:
    """Opaque keyset cursor: the last row's own sort key (§B4.5)."""
    raw = json.dumps([updated_at.isoformat(), str(notification_id)]).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    """Inverse of `encode_cursor`; raises `ValueError` on anything malformed."""
    raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
    updated_at_raw, id_raw = json.loads(raw)
    return datetime.fromisoformat(updated_at_raw), UUID(id_raw)


async def list_notifications(
    conn: Connection,
    *,
    member_id: UUID,
    unread_only: bool = False,
    updated_since: datetime | None = None,
    after: tuple[datetime, UUID] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """The caller's own notices, newest first; `after` continues from a previous page's cursor."""
    clauses = ["member_id = $1"]
    args: list[Any] = [member_id]
    if unread_only:
        clauses.append("read_at IS NULL")
    if updated_since is not None:
        args.append(updated_since)
        clauses.append(f"updated_at > ${len(args)}")
    if after is not None:
        after_updated_at, after_id = after
        args.extend([after_updated_at, after_id])
        clauses.append(f"(updated_at, id) < (${len(args) - 1}, ${len(args)})")
    args.append(limit)
    sql = (
        "SELECT id, member_id, event_type, template_key, title_key, body, link_entity_type, "  # nosec B608 # noqa: S608
        "link_entity_id, read_at, created_at, updated_at FROM public.notifications "
        f"WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC, id DESC LIMIT ${len(args)}"
    )
    rows = await conn.fetch(sql, *args)
    return [dict(row) for row in rows]


async def unread_count(conn: Connection, *, member_id: UUID) -> int:
    """How many of the caller's own notices are unread."""
    return int(
        await conn.fetchval(
            "SELECT count(*) FROM public.notifications WHERE member_id = $1 AND read_at IS NULL",
            member_id,
        )
    )


async def get_by_id(conn: Connection, *, notification_id: UUID) -> dict[str, Any] | None:
    """One notice by id, or None - whatever organization RLS already allows this connection to see."""
    row = await conn.fetchrow(
        "SELECT id, member_id, read_at FROM public.notifications WHERE id = $1", notification_id
    )
    return dict(row) if row is not None else None


async def mark_read(conn: Connection, *, notification_id: UUID) -> bool:
    """Set `read_at` if it is not already set; returns whether this call was the one that set it."""
    row = await conn.fetchrow(
        "UPDATE public.notifications SET read_at = now(), updated_at = now() "
        "WHERE id = $1 AND read_at IS NULL RETURNING id",
        notification_id,
    )
    return row is not None


async def mark_all_read(conn: Connection, *, member_id: UUID) -> int:
    """Mark every unread notice of `member_id` as read; returns how many were changed."""
    tag = await conn.execute(
        "UPDATE public.notifications SET read_at = now(), updated_at = now() "
        "WHERE member_id = $1 AND read_at IS NULL",
        member_id,
    )
    return int(tag.rsplit(" ", 1)[-1])
