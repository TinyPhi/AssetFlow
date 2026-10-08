# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The `Directory` port backed by PostgreSQL (§B6.3, M1.5-T2).

`conn` must already be stamped with the organization context (`worker_context`); every query here
relies on row-level security to stay inside that organization, the same as any other worker code.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.core.db import Connection
from app.core.permissions import ScopeType


@dataclass(frozen=True)
class PgDirectory:
    """A `Directory` backed by one organization-scoped connection."""

    conn: Connection

    async def team_member_ids(self, team_id: UUID) -> set[UUID]:
        rows = await self.conn.fetch(
            "SELECT member_id FROM public.team_members "
            "WHERE team_id = $1 AND (valid_to IS NULL OR valid_to > now())",
            team_id,
        )
        return {row["member_id"] for row in rows}

    async def members_with_role(
        self, role_key: str, scope_type: ScopeType, scope_id: UUID | None
    ) -> set[UUID]:
        if scope_type == ScopeType.ORGANIZATION:
            rows = await self.conn.fetch(
                "SELECT member_id FROM public.role_grants "
                "WHERE role_key = $1 AND scope_type = 'organization' AND member_id IS NOT NULL "
                "AND (expires_at IS NULL OR expires_at > now())",
                role_key,
            )
        elif scope_type == ScopeType.TEAM:
            rows = await self.conn.fetch(
                "SELECT member_id FROM public.role_grants "
                "WHERE role_key = $1 AND scope_type = 'team' AND scope_id = $2 AND member_id IS NOT NULL "
                "AND (expires_at IS NULL OR expires_at > now())",
                role_key,
                scope_id,
            )
        elif scope_type == ScopeType.ORG_UNIT:
            # A grant at a parent org unit covers every org unit under it (§B5): the grant's own
            # unit path must be an ancestor of (or equal to) the target unit's path.
            rows = await self.conn.fetch(
                "SELECT rg.member_id FROM public.role_grants rg "
                "JOIN public.org_units granted ON granted.id = rg.scope_id "
                "JOIN public.org_units target ON target.id = $2 "
                "WHERE rg.role_key = $1 AND rg.scope_type = 'org_unit' AND rg.member_id IS NOT NULL "
                "AND (rg.expires_at IS NULL OR rg.expires_at > now()) "
                "AND target.path <@ granted.path",
                role_key,
                scope_id,
            )
        else:
            return set()
        return {row["member_id"] for row in rows}

    async def is_active(self, member_id: UUID) -> bool:
        status = await self.conn.fetchval("SELECT status FROM public.members WHERE id = $1", member_id)
        return bool(status == "active")
