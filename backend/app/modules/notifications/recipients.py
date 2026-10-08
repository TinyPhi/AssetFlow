# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Where to reach a member, looked up at send time only (§B6.3 rule 3, §C5.2).

The delivery log keeps the member id as its target; the address is read from the member record in
one short transaction right before the channel connects, held in memory for that send, and never
written to a log, a trace, a metric tag or a table.
"""

from __future__ import annotations

from uuid import UUID

from app.channels.base import Recipient
from app.core.db import Pool, worker_context

__all__ = ["PgRecipientResolver"]


class PgRecipientResolver:
    """A `RecipientResolver` backed by the `members` table, under one organization's context."""

    def __init__(self, pool: Pool, organization_id: UUID) -> None:
        self._pool = pool
        self._organization_id = organization_id

    async def resolve(self, member_id: str) -> Recipient | None:
        """The active member's address, or None (unknown, invited, suspended or left)."""
        try:
            member_uuid = UUID(member_id)
        except ValueError:
            return None
        async with worker_context(self._pool, self._organization_id) as conn:
            row = await conn.fetchrow(
                "SELECT email, display_name FROM public.members WHERE id = $1 AND status = 'active'",
                member_uuid,
            )
        if row is None:
            return None
        return Recipient(address=row["email"], display_name=row["display_name"])
