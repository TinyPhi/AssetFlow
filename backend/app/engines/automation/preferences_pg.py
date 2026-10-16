# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The `Preferences` port backed by PostgreSQL (§B6.3 rule 7, M1.5-T7).

`conn` must already be stamped with the organization context (`worker_context`); row-level security
keeps the read inside that organization. One query covers every member and event type of a batch.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.core.db import Connection


@dataclass(frozen=True)
class PgPreferences:
    """A `Preferences` backed by one organization-scoped connection."""

    conn: Connection

    async def disabled(self, member_ids: set[UUID], event_types: set[str]) -> set[tuple[UUID, str, str]]:
        rows = await self.conn.fetch(
            "SELECT member_id, event_type, channel_key FROM public.notification_preferences "
            "WHERE enabled = false AND member_id = ANY($1) AND event_type = ANY($2)",
            list(member_ids),
            list(event_types),
        )
        return {(row["member_id"], row["event_type"], row["channel_key"]) for row in rows}
