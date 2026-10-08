# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Asset component repository: raw SQL against `public.asset_components` (§C4.4, P8-09).

A child has at most one *current* parent (partial unique index on `detached_at IS NULL`, P8-03);
a detached link stays as history. The parent chain and the descendant set are walked with
recursive CTEs over current links only; both use `UNION`, so a (never expected) cycle in the data
ends instead of looping.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg

from app.core.ids import uuid7
from app.core.permissions import ScopeFilter

type DbConn = asyncpg.Connection[asyncpg.Record] | asyncpg.pool.PoolConnectionProxy[asyncpg.Record]

__all__ = ["ComponentRepository"]

_LINK_COLUMNS = "id, organization_id, parent_asset_id, child_asset_id, attached_at, detached_at, version"


class ComponentRepository:
    async def lock_attachments(self, conn: DbConn, *, organization_id: UUID) -> None:
        """Serialize attaches inside one organization so two attaches that are each cycle-free on
        their own cannot together close a loop (the row locks only cover the two assets of one call)."""
        await conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended('asset_components:' || $1::text, 0))",
            str(organization_id),
        )

    async def get_current_for_child(
        self, conn: DbConn, *, organization_id: UUID, child_asset_id: UUID
    ) -> asyncpg.Record | None:
        return await conn.fetchrow(
            f"SELECT {_LINK_COLUMNS} FROM public.asset_components "  # nosec B608  # noqa: S608
            "WHERE organization_id = $1 AND child_asset_id = $2 AND detached_at IS NULL",
            organization_id,
            child_asset_id,
        )

    async def get_current_link(
        self, conn: DbConn, *, organization_id: UUID, parent_asset_id: UUID, child_asset_id: UUID
    ) -> asyncpg.Record | None:
        return await conn.fetchrow(
            f"SELECT {_LINK_COLUMNS} FROM public.asset_components "  # nosec B608  # noqa: S608
            "WHERE organization_id = $1 AND parent_asset_id = $2 AND child_asset_id = $3 "
            "AND detached_at IS NULL FOR UPDATE",
            organization_id,
            parent_asset_id,
            child_asset_id,
        )

    async def ancestor_ids(self, conn: DbConn, *, organization_id: UUID, asset_id: UUID) -> set[UUID]:
        """Every asset above `asset_id` through current links."""
        rows = await conn.fetch(
            "WITH RECURSIVE up(asset_id) AS ("
            " SELECT parent_asset_id FROM public.asset_components"
            "  WHERE organization_id = $1 AND child_asset_id = $2 AND detached_at IS NULL"
            " UNION"
            " SELECT c.parent_asset_id FROM public.asset_components c"
            "  JOIN up ON c.child_asset_id = up.asset_id"
            "  WHERE c.organization_id = $1 AND c.detached_at IS NULL"
            ") SELECT asset_id FROM up",
            organization_id,
            asset_id,
        )
        return {r["asset_id"] for r in rows}

    async def descendant_ids(self, conn: DbConn, *, organization_id: UUID, asset_id: UUID) -> list[UUID]:
        """Every current descendant of `asset_id`, in id order (the order rows are locked in)."""
        rows = await conn.fetch(
            "WITH RECURSIVE down(asset_id) AS ("
            " SELECT child_asset_id FROM public.asset_components"
            "  WHERE organization_id = $1 AND parent_asset_id = $2 AND detached_at IS NULL"
            " UNION"
            " SELECT c.child_asset_id FROM public.asset_components c"
            "  JOIN down ON c.parent_asset_id = down.asset_id"
            "  WHERE c.organization_id = $1 AND c.detached_at IS NULL"
            ") SELECT asset_id FROM down ORDER BY asset_id",
            organization_id,
            asset_id,
        )
        return [r["asset_id"] for r in rows]

    async def insert(
        self, conn: DbConn, *, organization_id: UUID, parent_asset_id: UUID, child_asset_id: UUID
    ) -> asyncpg.Record:
        row = await conn.fetchrow(
            f"INSERT INTO public.asset_components (id, organization_id, parent_asset_id, child_asset_id) "  # nosec B608  # noqa: S608
            f"VALUES ($1, $2, $3, $4) RETURNING {_LINK_COLUMNS}",
            uuid7(),
            organization_id,
            parent_asset_id,
            child_asset_id,
        )
        assert row is not None  # noqa: S101 - INSERT ... RETURNING always returns one row
        return row

    async def detach(self, conn: DbConn, *, organization_id: UUID, component_id: UUID) -> asyncpg.Record:
        row = await conn.fetchrow(
            f"UPDATE public.asset_components SET detached_at = now(), updated_at = now(), "  # nosec B608  # noqa: S608
            "version = version + 1 WHERE organization_id = $1 AND id = $2 "
            f"RETURNING {_LINK_COLUMNS}",
            organization_id,
            component_id,
        )
        assert row is not None  # noqa: S101 - the link was just read under lock
        return row

    async def list_children(
        self,
        conn: DbConn,
        *,
        organization_id: UUID,
        scope_filter: ScopeFilter,
        parent_asset_id: UUID,
        include_history: bool = False,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Direct children of one parent that fall inside `scope_filter` (a child the caller may
        not read is left out, as in any list)."""
        where_history = "" if include_history else "AND c.detached_at IS NULL "
        rows = await conn.fetch(
            "SELECT c.id AS component_id, c.parent_asset_id, c.child_asset_id, c.attached_at, "  # nosec B608  # noqa: S608
            "c.detached_at, c.version, a.tag, a.name, a.status, a.owner_org_unit_path::text AS path, "
            "a.holder_member_id, a.holder_team_id "
            "FROM public.asset_components c "
            "JOIN public.assets a ON a.organization_id = c.organization_id AND a.id = c.child_asset_id "
            f"WHERE c.organization_id = $1 AND c.parent_asset_id = $2 {where_history}"
            "ORDER BY c.attached_at, c.id LIMIT $3",
            organization_id,
            parent_asset_id,
            limit,
        )
        out: list[dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            holder_member = data.pop("holder_member_id")
            holder_team = data.pop("holder_team_id")
            if scope_filter.covers(
                owner_org_unit_path=data.pop("path"),
                team_id=str(holder_team) if holder_team else None,
                holder_id=str(holder_member) if holder_member else None,
            ):
                out.append(data)
        return out

    async def get_parent_summary(
        self, conn: DbConn, *, organization_id: UUID, child_asset_id: UUID
    ) -> asyncpg.Record | None:
        """The current parent's `{id, tag, name}` plus the columns a scope check needs."""
        return await conn.fetchrow(
            "SELECT p.id, p.tag, p.name, p.owner_org_unit_path::text AS owner_org_unit_path, "
            "p.holder_member_id, p.holder_team_id "
            "FROM public.asset_components c "
            "JOIN public.assets p ON p.organization_id = c.organization_id AND p.id = c.parent_asset_id "
            "WHERE c.organization_id = $1 AND c.child_asset_id = $2 AND c.detached_at IS NULL",
            organization_id,
            child_asset_id,
        )

    async def count_children(self, conn: DbConn, *, organization_id: UUID, parent_asset_id: UUID) -> int:
        value = await conn.fetchval(
            "SELECT count(*) FROM public.asset_components "
            "WHERE organization_id = $1 AND parent_asset_id = $2 AND detached_at IS NULL",
            organization_id,
            parent_asset_id,
        )
        return int(value)
