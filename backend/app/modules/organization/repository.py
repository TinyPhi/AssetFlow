# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Organization structure and access repositories (§B5.2, §C4.4, M1.4-T4)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import asyncpg

from app.core.permissions import ScopeFilter

type DbConn = asyncpg.Connection[asyncpg.Record] | asyncpg.pool.PoolConnectionProxy[asyncpg.Record]

__all__ = [
    "LocationRepository",
    "OrgUnitRepository",
    "TeamMemberRepository",
    "TeamRepository",
    "to_ltree_label",
]


def to_ltree_label(code: str) -> str:
    """Convert a business code into a valid PostgreSQL ltree label."""
    label = re.sub(r"[^a-zA-Z0-9_]", "_", code.strip().lower())
    if not label:
        raise ValueError("Code produces an empty ltree label")
    return label


# ==============================================================================
# Org Unit Repository
# ==============================================================================


class OrgUnitRepository:
    """Database repository for organizational units (tree hierarchy via ltree)."""

    async def get_by_id(
        self, conn: DbConn, *, organization_id: UUID, unit_id: UUID, for_update: bool = False
    ) -> asyncpg.Record | None:
        lock = " FOR UPDATE" if for_update else ""
        sql = (
            f"SELECT id, organization_id, parent_id, path::text AS path, type, code, name, "  # noqa: S608
            f"manager_member_id, status, version, created_at, updated_at "
            f"FROM public.org_units WHERE organization_id = $1 AND id = $2{lock}"
        )
        return await conn.fetchrow(sql, organization_id, unit_id)

    async def get_by_code(
        self, conn: DbConn, *, organization_id: UUID, code: str, for_update: bool = False
    ) -> asyncpg.Record | None:
        lock = " FOR UPDATE" if for_update else ""
        sql = (
            f"SELECT id, organization_id, parent_id, path::text AS path, type, code, name, "  # noqa: S608
            f"manager_member_id, status, version, created_at, updated_at "
            f"FROM public.org_units WHERE organization_id = $1 AND code = $2{lock}"
        )
        return await conn.fetchrow(sql, organization_id, code)

    async def create(
        self,
        conn: DbConn,
        *,
        unit_id: UUID,
        organization_id: UUID,
        parent_id: UUID | None,
        path: str,
        unit_type: str,
        code: str,
        name: str,
        manager_member_id: UUID | None = None,
    ) -> asyncpg.Record:
        return await conn.fetchrow(
            "INSERT INTO public.org_units "
            "(id, organization_id, parent_id, path, type, code, name, manager_member_id, "
            "status, version) "
            "VALUES ($1, $2, $3, $4::ltree, $5, $6, $7, $8, 'active', 1) "
            "RETURNING id, organization_id, parent_id, path::text AS path, type, code, name, "
            "manager_member_id, status, version, created_at, updated_at",
            unit_id,
            organization_id,
            parent_id,
            path,
            unit_type,
            code,
            name,
            manager_member_id,
        )  # type: ignore[return-value]

    async def update(
        self,
        conn: DbConn,
        *,
        organization_id: UUID,
        unit_id: UUID,
        version: int,
        name: str | None = None,
        unit_type: str | None = None,
        manager_member_id: UUID | None = None,
        clear_manager: bool = False,
    ) -> asyncpg.Record | None:
        sets = ["version = version + 1", "updated_at = now()"]
        args: list[Any] = [organization_id, unit_id, version]

        if name is not None:
            args.append(name)
            sets.append(f"name = ${len(args)}")
        if unit_type is not None:
            args.append(unit_type)
            sets.append(f"type = ${len(args)}")
        if clear_manager:
            sets.append("manager_member_id = NULL")
        elif manager_member_id is not None:
            args.append(manager_member_id)
            sets.append(f"manager_member_id = ${len(args)}")

        sql = (
            f"UPDATE public.org_units SET {', '.join(sets)} "  # noqa: S608
            f"WHERE organization_id = $1 AND id = $2 AND version = $3 "
            f"RETURNING id, organization_id, parent_id, path::text AS path, type, code, name, "
            f"manager_member_id, status, version, created_at, updated_at"
        )
        return await conn.fetchrow(sql, *args)

    async def move(
        self,
        conn: DbConn,
        *,
        organization_id: UUID,
        unit_id: UUID,
        version: int,
        new_parent_id: UUID,
        old_path: str,
        new_path: str,
    ) -> asyncpg.Record | None:
        """Move a node and cascade path updates to all descendant org units in one transaction."""
        await conn.execute(
            "UPDATE public.org_units "
            "SET path = $1::ltree || subpath(path, nlevel($2::ltree)), updated_at = now() "
            "WHERE organization_id = $3 AND path <@ $2::ltree AND id != $4",
            new_path,
            old_path,
            organization_id,
            unit_id,
        )

        return await conn.fetchrow(
            "UPDATE public.org_units "
            "SET parent_id = $1, path = $2::ltree, version = version + 1, updated_at = now() "
            "WHERE organization_id = $3 AND id = $4 AND version = $5 "
            "RETURNING id, organization_id, parent_id, path::text AS path, type, code, name, "
            "manager_member_id, status, version, created_at, updated_at",
            new_parent_id,
            new_path,
            organization_id,
            unit_id,
            version,
        )

    async def archive(
        self,
        conn: DbConn,
        *,
        organization_id: UUID,
        unit_id: UUID,
        version: int,
    ) -> asyncpg.Record | None:
        return await conn.fetchrow(
            "UPDATE public.org_units "
            "SET status = 'archived', version = version + 1, updated_at = now() "
            "WHERE organization_id = $1 AND id = $2 AND version = $3 "
            "RETURNING id, organization_id, parent_id, path::text AS path, type, code, name, "
            "manager_member_id, status, version, created_at, updated_at",
            organization_id,
            unit_id,
            version,
        )

    async def count_active_children(self, conn: DbConn, *, organization_id: UUID, unit_id: UUID) -> int:
        val: int | None = await conn.fetchval(
            "SELECT count(*) FROM public.org_units "
            "WHERE organization_id = $1 AND parent_id = $2 AND status = 'active'",
            organization_id,
            unit_id,
        )
        return val or 0

    async def count_active_members(self, conn: DbConn, *, organization_id: UUID, unit_id: UUID) -> int:
        primary: int = (
            await conn.fetchval(
                "SELECT count(*) FROM public.members "
                "WHERE organization_id = $1 AND primary_org_unit_id = $2 "
                "AND status IN ('invited', 'active')",
                organization_id,
                unit_id,
            )
            or 0
        )
        secondary: int = (
            await conn.fetchval(
                "SELECT count(*) FROM public.member_org_units mou "
                "JOIN public.members m "
                "ON m.id = mou.member_id AND m.organization_id = mou.organization_id "
                "WHERE mou.organization_id = $1 AND mou.org_unit_id = $2 "
                "AND m.status IN ('invited', 'active')",
                organization_id,
                unit_id,
            )
            or 0
        )
        return primary + secondary

    async def count_active_teams(self, conn: DbConn, *, organization_id: UUID, unit_id: UUID) -> int:
        val: int | None = await conn.fetchval(
            "SELECT count(*) FROM public.teams "
            "WHERE organization_id = $1 AND owning_org_unit_id = $2 AND status = 'active'",
            organization_id,
            unit_id,
        )
        return val or 0

    async def list(
        self,
        conn: DbConn,
        *,
        organization_id: UUID,
        scope_filter: ScopeFilter,
        status: str | None = None,
        parent_id: UUID | None = None,
    ) -> list[asyncpg.Record]:
        if scope_filter.is_empty:
            return []

        clauses = ["ou.organization_id = $1"]
        args: list[Any] = [organization_id]

        if status is not None:
            args.append(status)
            clauses.append(f"ou.status = ${len(args)}")

        if parent_id is not None:
            args.append(parent_id)
            clauses.append(f"ou.parent_id = ${len(args)}")

        if not scope_filter.organization:
            branches: list[str] = []
            if scope_filter.org_unit_paths:
                args.append(list(scope_filter.org_unit_paths))
                branches.append(
                    f"SELECT id FROM public.org_units "  # noqa: S608
                    f"WHERE organization_id = $1 AND (path <@ ANY(${len(args)}::ltree[]))"
                )
            if scope_filter.team_ids:
                team_uuids = [UUID(t) for t in scope_filter.team_ids if _is_uuid(t)]
                if team_uuids:
                    args.append(team_uuids)
                    branches.append(
                        f"SELECT owning_org_unit_id AS id FROM public.teams "  # noqa: S608
                        f"WHERE organization_id = $1 AND id = ANY(${len(args)}::uuid[]) "
                        f"AND owning_org_unit_id IS NOT NULL"
                    )
            if not branches:
                return []
            allowed_union = " UNION ALL ".join(branches)
            clauses.append(f"ou.id IN ({allowed_union})")

        sql = (
            f"SELECT ou.id, ou.organization_id, ou.parent_id, ou.path::text AS path, "  # noqa: S608
            f"ou.type, ou.code, ou.name, ou.manager_member_id, ou.status, ou.version, "
            f"ou.created_at, ou.updated_at "
            f"FROM public.org_units ou WHERE {' AND '.join(clauses)} "
            f"ORDER BY ou.path ASC"
        )
        return await conn.fetch(sql, *args)


# ==============================================================================
# Location Repository
# ==============================================================================


class LocationRepository:
    """Database repository for physical locations (tree hierarchy via ltree)."""

    async def get_by_id(
        self, conn: DbConn, *, organization_id: UUID, location_id: UUID, for_update: bool = False
    ) -> asyncpg.Record | None:
        lock = " FOR UPDATE" if for_update else ""
        sql = (
            f"SELECT id, organization_id, parent_id, path::text AS path, type, code, name, "  # noqa: S608
            f"address, version, created_at, updated_at "
            f"FROM public.locations WHERE organization_id = $1 AND id = $2{lock}"
        )
        return await conn.fetchrow(sql, organization_id, location_id)

    async def get_by_code(
        self, conn: DbConn, *, organization_id: UUID, code: str, for_update: bool = False
    ) -> asyncpg.Record | None:
        lock = " FOR UPDATE" if for_update else ""
        sql = (
            f"SELECT id, organization_id, parent_id, path::text AS path, type, code, name, "  # noqa: S608
            f"address, version, created_at, updated_at "
            f"FROM public.locations WHERE organization_id = $1 AND code = $2{lock}"
        )
        return await conn.fetchrow(sql, organization_id, code)

    async def create(
        self,
        conn: DbConn,
        *,
        location_id: UUID,
        organization_id: UUID,
        parent_id: UUID | None,
        path: str,
        loc_type: str,
        code: str,
        name: str,
        address: dict[str, Any] | None = None,
    ) -> asyncpg.Record:
        return await conn.fetchrow(
            "INSERT INTO public.locations "
            "(id, organization_id, parent_id, path, type, code, name, address, version) "
            "VALUES ($1, $2, $3, $4::ltree, $5, $6, $7, $8::jsonb, 1) "
            "RETURNING id, organization_id, parent_id, path::text AS path, type, code, name, "
            "address, version, created_at, updated_at",
            location_id,
            organization_id,
            parent_id,
            path,
            loc_type,
            code,
            name,
            json.dumps(address or {}),
        )  # type: ignore[return-value]

    async def update(
        self,
        conn: DbConn,
        *,
        organization_id: UUID,
        location_id: UUID,
        version: int,
        name: str | None = None,
        loc_type: str | None = None,
        address: dict[str, Any] | None = None,
    ) -> asyncpg.Record | None:
        sets = ["version = version + 1", "updated_at = now()"]
        args: list[Any] = [organization_id, location_id, version]

        if name is not None:
            args.append(name)
            sets.append(f"name = ${len(args)}")
        if loc_type is not None:
            args.append(loc_type)
            sets.append(f"type = ${len(args)}")
        if address is not None:
            args.append(json.dumps(address))
            sets.append(f"address = ${len(args)}::jsonb")

        sql = (
            f"UPDATE public.locations SET {', '.join(sets)} "  # noqa: S608
            f"WHERE organization_id = $1 AND id = $2 AND version = $3 "
            f"RETURNING id, organization_id, parent_id, path::text AS path, type, code, name, "
            f"address, version, created_at, updated_at"
        )
        return await conn.fetchrow(sql, *args)

    async def move(
        self,
        conn: DbConn,
        *,
        organization_id: UUID,
        location_id: UUID,
        version: int,
        new_parent_id: UUID | None,
        old_path: str,
        new_path: str,
    ) -> asyncpg.Record | None:
        """Move a location and cascade path updates to all sub-locations."""
        await conn.execute(
            "UPDATE public.locations "
            "SET path = $1::ltree || subpath(path, nlevel($2::ltree)), updated_at = now() "
            "WHERE organization_id = $3 AND path <@ $2::ltree AND id != $4",
            new_path,
            old_path,
            organization_id,
            location_id,
        )

        return await conn.fetchrow(
            "UPDATE public.locations "
            "SET parent_id = $1, path = $2::ltree, version = version + 1, updated_at = now() "
            "WHERE organization_id = $3 AND id = $4 AND version = $5 "
            "RETURNING id, organization_id, parent_id, path::text AS path, type, code, name, "
            "address, version, created_at, updated_at",
            new_parent_id,
            new_path,
            organization_id,
            location_id,
            version,
        )

    async def delete(
        self,
        conn: DbConn,
        *,
        organization_id: UUID,
        location_id: UUID,
        version: int,
    ) -> bool:
        res = await conn.execute(
            "DELETE FROM public.locations WHERE organization_id = $1 AND id = $2 AND version = $3",
            organization_id,
            location_id,
            version,
        )
        return res == "DELETE 1"

    async def count_children(self, conn: DbConn, *, organization_id: UUID, location_id: UUID) -> int:
        val: int | None = await conn.fetchval(
            "SELECT count(*) FROM public.locations WHERE organization_id = $1 AND parent_id = $2",
            organization_id,
            location_id,
        )
        return val or 0

    async def list(
        self,
        conn: DbConn,
        *,
        organization_id: UUID,
        scope_filter: ScopeFilter,
        parent_id: UUID | None = None,
    ) -> list[asyncpg.Record]:
        if scope_filter.is_empty:
            return []

        clauses = ["organization_id = $1"]
        args: list[Any] = [organization_id]

        if parent_id is not None:
            args.append(parent_id)
            clauses.append(f"parent_id = ${len(args)}")

        sql = (
            f"SELECT id, organization_id, parent_id, path::text AS path, type, code, name, "  # noqa: S608
            f"address, version, created_at, updated_at "
            f"FROM public.locations WHERE {' AND '.join(clauses)} "
            f"ORDER BY path ASC"
        )
        return await conn.fetch(sql, *args)


# ==============================================================================
# Team Repository
# ==============================================================================


class TeamRepository:
    """Database repository for teams."""

    async def get_by_id(
        self, conn: DbConn, *, organization_id: UUID, team_id: UUID, for_update: bool = False
    ) -> asyncpg.Record | None:
        lock = " FOR UPDATE" if for_update else ""
        sql = (
            f"SELECT id, organization_id, code, name, owning_org_unit_id, type, skills, "  # noqa: S608
            f"working_calendar_id, status, version, created_at, updated_at "
            f"FROM public.teams WHERE organization_id = $1 AND id = $2{lock}"
        )
        return await conn.fetchrow(sql, organization_id, team_id)

    async def get_by_code(
        self, conn: DbConn, *, organization_id: UUID, code: str, for_update: bool = False
    ) -> asyncpg.Record | None:
        lock = " FOR UPDATE" if for_update else ""
        sql = (
            f"SELECT id, organization_id, code, name, owning_org_unit_id, type, skills, "  # noqa: S608
            f"working_calendar_id, status, version, created_at, updated_at "
            f"FROM public.teams WHERE organization_id = $1 AND code = $2{lock}"
        )
        return await conn.fetchrow(sql, organization_id, code)

    async def create(
        self,
        conn: DbConn,
        *,
        team_id: UUID,
        organization_id: UUID,
        code: str,
        name: str,
        team_type: str,
        owning_org_unit_id: UUID | None = None,
        skills: list[str] | None = None,
        working_calendar_id: UUID | None = None,
    ) -> asyncpg.Record:
        return await conn.fetchrow(
            "INSERT INTO public.teams "
            "(id, organization_id, code, name, owning_org_unit_id, type, skills, "
            "working_calendar_id, status, version) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'active', 1) "
            "RETURNING id, organization_id, code, name, owning_org_unit_id, type, skills, "
            "working_calendar_id, status, version, created_at, updated_at",
            team_id,
            organization_id,
            code,
            name,
            owning_org_unit_id,
            team_type,
            skills or [],
            working_calendar_id,
        )  # type: ignore[return-value]

    async def update(
        self,
        conn: DbConn,
        *,
        organization_id: UUID,
        team_id: UUID,
        version: int,
        name: str | None = None,
        team_type: str | None = None,
        owning_org_unit_id: UUID | None = None,
        clear_owning_org_unit: bool = False,
        skills: list[str] | None = None,
        working_calendar_id: UUID | None = None,
        clear_working_calendar: bool = False,
    ) -> asyncpg.Record | None:
        sets = ["version = version + 1", "updated_at = now()"]
        args: list[Any] = [organization_id, team_id, version]

        if name is not None:
            args.append(name)
            sets.append(f"name = ${len(args)}")
        if team_type is not None:
            args.append(team_type)
            sets.append(f"type = ${len(args)}")
        if clear_owning_org_unit:
            sets.append("owning_org_unit_id = NULL")
        elif owning_org_unit_id is not None:
            args.append(owning_org_unit_id)
            sets.append(f"owning_org_unit_id = ${len(args)}")
        if skills is not None:
            args.append(skills)
            sets.append(f"skills = ${len(args)}")
        if clear_working_calendar:
            sets.append("working_calendar_id = NULL")
        elif working_calendar_id is not None:
            args.append(working_calendar_id)
            sets.append(f"working_calendar_id = ${len(args)}")

        sql = (
            f"UPDATE public.teams SET {', '.join(sets)} "  # noqa: S608
            f"WHERE organization_id = $1 AND id = $2 AND version = $3 "
            f"RETURNING id, organization_id, code, name, owning_org_unit_id, type, skills, "
            f"working_calendar_id, status, version, created_at, updated_at"
        )
        return await conn.fetchrow(sql, *args)

    async def archive(
        self,
        conn: DbConn,
        *,
        organization_id: UUID,
        team_id: UUID,
        version: int,
    ) -> asyncpg.Record | None:
        return await conn.fetchrow(
            "UPDATE public.teams "
            "SET status = 'archived', version = version + 1, updated_at = now() "
            "WHERE organization_id = $1 AND id = $2 AND version = $3 "
            "RETURNING id, organization_id, code, name, owning_org_unit_id, type, skills, "
            "working_calendar_id, status, version, created_at, updated_at",
            organization_id,
            team_id,
            version,
        )

    async def count_active_members(self, conn: DbConn, *, organization_id: UUID, team_id: UUID) -> int:
        now = datetime.now(UTC)
        val: int | None = await conn.fetchval(
            "SELECT count(*) FROM public.team_members tm "
            "JOIN public.members m ON m.id = tm.member_id AND m.organization_id = tm.organization_id "
            "WHERE tm.organization_id = $1 AND tm.team_id = $2 "
            "AND (tm.valid_to IS NULL OR tm.valid_to > $3) AND m.status IN ('invited', 'active')",
            organization_id,
            team_id,
            now,
        )
        return val or 0

    async def list(
        self,
        conn: DbConn,
        *,
        organization_id: UUID,
        scope_filter: ScopeFilter,
        status: str | None = None,
        owning_org_unit_id: UUID | None = None,
    ) -> list[asyncpg.Record]:
        if scope_filter.is_empty:
            return []

        clauses = ["t.organization_id = $1"]
        args: list[Any] = [organization_id]

        if status is not None:
            args.append(status)
            clauses.append(f"t.status = ${len(args)}")

        if owning_org_unit_id is not None:
            args.append(owning_org_unit_id)
            clauses.append(f"t.owning_org_unit_id = ${len(args)}")

        if not scope_filter.organization:
            branches: list[str] = []
            if scope_filter.team_ids:
                team_uuids = [UUID(t) for t in scope_filter.team_ids if _is_uuid(t)]
                if team_uuids:
                    args.append(team_uuids)
                    branches.append(
                        f"SELECT id FROM public.teams "  # noqa: S608
                        f"WHERE organization_id = $1 AND id = ANY(${len(args)}::uuid[])"
                    )
            if scope_filter.org_unit_paths:
                args.append(list(scope_filter.org_unit_paths))
                branches.append(
                    f"SELECT t.id FROM public.teams t "  # noqa: S608
                    f"JOIN public.org_units ou "
                    f"ON ou.id = t.owning_org_unit_id AND ou.organization_id = t.organization_id "
                    f"WHERE t.organization_id = $1 AND (ou.path <@ ANY(${len(args)}::ltree[]))"
                )
            if not branches:
                return []
            allowed_union = " UNION ALL ".join(branches)
            clauses.append(f"t.id IN ({allowed_union})")

        sql = (
            f"SELECT t.id, t.organization_id, t.code, t.name, t.owning_org_unit_id, t.type, "  # noqa: S608
            f"t.skills, t.working_calendar_id, t.status, t.version, t.created_at, t.updated_at "
            f"FROM public.teams t WHERE {' AND '.join(clauses)} "
            f"ORDER BY t.name ASC"
        )
        return await conn.fetch(sql, *args)


# ==============================================================================
# Team Member Repository
# ==============================================================================


class TeamMemberRepository:
    """Database repository for team member assignments."""

    async def get_by_id(
        self, conn: DbConn, *, organization_id: UUID, record_id: UUID
    ) -> asyncpg.Record | None:
        return await conn.fetchrow(
            "SELECT id, organization_id, team_id, member_id, team_role, valid_from, valid_to, "
            "created_at, updated_at FROM public.team_members "
            "WHERE organization_id = $1 AND id = $2",
            organization_id,
            record_id,
        )

    async def get_by_team_and_member(
        self, conn: DbConn, *, organization_id: UUID, team_id: UUID, member_id: UUID
    ) -> asyncpg.Record | None:
        return await conn.fetchrow(
            "SELECT id, organization_id, team_id, member_id, team_role, valid_from, valid_to, "
            "created_at, updated_at FROM public.team_members "
            "WHERE organization_id = $1 AND team_id = $2 AND member_id = $3",
            organization_id,
            team_id,
            member_id,
        )

    async def add(
        self,
        conn: DbConn,
        *,
        record_id: UUID,
        organization_id: UUID,
        team_id: UUID,
        member_id: UUID,
        team_role: str = "member",
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
    ) -> asyncpg.Record:
        vf = valid_from or datetime.now(UTC)
        return await conn.fetchrow(
            "INSERT INTO public.team_members "
            "(id, organization_id, team_id, member_id, team_role, valid_from, valid_to) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7) "
            "RETURNING id, organization_id, team_id, member_id, team_role, valid_from, valid_to, "
            "created_at, updated_at",
            record_id,
            organization_id,
            team_id,
            member_id,
            team_role,
            vf,
            valid_to,
        )  # type: ignore[return-value]

    async def update(
        self,
        conn: DbConn,
        *,
        organization_id: UUID,
        team_id: UUID,
        member_id: UUID,
        team_role: str | None = None,
        valid_to: datetime | None = None,
    ) -> asyncpg.Record | None:
        sets = ["updated_at = now()"]
        args: list[Any] = [organization_id, team_id, member_id]

        if team_role is not None:
            args.append(team_role)
            sets.append(f"team_role = ${len(args)}")
        if valid_to is not None:
            args.append(valid_to)
            sets.append(f"valid_to = ${len(args)}")

        sql = (
            f"UPDATE public.team_members SET {', '.join(sets)} "  # noqa: S608
            f"WHERE organization_id = $1 AND team_id = $2 AND member_id = $3 "
            f"RETURNING id, organization_id, team_id, member_id, team_role, valid_from, valid_to, "
            f"created_at, updated_at"
        )
        return await conn.fetchrow(sql, *args)

    async def remove(self, conn: DbConn, *, organization_id: UUID, team_id: UUID, member_id: UUID) -> bool:
        res = await conn.execute(
            "DELETE FROM public.team_members WHERE organization_id = $1 AND team_id = $2 AND member_id = $3",
            organization_id,
            team_id,
            member_id,
        )
        return res == "DELETE 1"

    async def list_by_team(
        self, conn: DbConn, *, organization_id: UUID, team_id: UUID
    ) -> list[asyncpg.Record]:
        return await conn.fetch(
            "SELECT id, organization_id, team_id, member_id, team_role, valid_from, valid_to, "
            "created_at, updated_at FROM public.team_members "
            "WHERE organization_id = $1 AND team_id = $2 "
            "ORDER BY created_at ASC",
            organization_id,
            team_id,
        )


def _is_uuid(val: str) -> bool:
    try:
        UUID(val)
        return True
    except ValueError:
        return False
