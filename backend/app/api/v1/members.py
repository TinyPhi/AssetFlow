# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Members and access view endpoints (§B5.8, M1.6-T4)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from app.api.deps import get_db, permission_extra, require_member
from app.api.v1.caller import request_id
from app.core.envelope import success_response
from app.core.permissions import ScopeFilter
from app.core.problems import NotFoundError
from app.core.scope import MemberContext, default_scope_resolver
from app.modules.organization.profile import effective_permissions
from app.modules.organization.provisioning import load_member_context

router = APIRouter(prefix="/members", tags=["Members"])


def _is_uuid(value: str) -> bool:
    """Small, pure duplicate of organization.repository's helper (which is private to that module,
    import-linter contract `repo-organization`; app.api may not import app.modules.organization.repository).
    """
    try:
        UUID(value)
        return True
    except ValueError:
        return False


def _allowed_members_sql(scope_filter: ScopeFilter, args: list[Any]) -> str | None:
    """The member ids a restricted scope may see, as a sub-select (``$1`` is the organization id).

    ``None`` means the whole organization; an empty string means nobody. Values are appended to
    ``args`` and bound, never interpolated.
    """
    if scope_filter.organization:
        return None
    branches: list[str] = []
    if scope_filter.org_unit_paths:
        args.append(list(scope_filter.org_unit_paths))
        branches.append(
            "SELECT mou.member_id FROM public.member_org_units mou "  # nosec B608 # noqa: S608
            "JOIN public.org_units ou ON ou.id = mou.org_unit_id "
            f"WHERE mou.organization_id = $1 AND (ou.path <@ ANY(${len(args)}::ltree[]))"
        )
    if scope_filter.team_ids:
        team_uuids = [UUID(t) for t in scope_filter.team_ids if _is_uuid(t)]
        if team_uuids:
            args.append(team_uuids)
            branches.append(
                "SELECT tm.member_id FROM public.team_members tm "  # nosec B608 # noqa: S608
                f"WHERE tm.organization_id = $1 AND tm.team_id = ANY(${len(args)}::uuid[]) "
                "AND (tm.valid_to IS NULL OR tm.valid_to > now())"
            )
    if scope_filter.member_id:
        args.append(UUID(scope_filter.member_id))
        branches.append(f"SELECT ${len(args)}::uuid")
    return " UNION ALL ".join(branches)


async def _require_member_in_scope(
    conn: Any, caller: MemberContext, permission: str, member_id: UUID
) -> None:
    """404 unless ``member_id`` is inside the caller's scope for ``permission`` (same rule as the list)."""
    scope_filter = default_scope_resolver.resolve_scope_filter(caller, permission)
    if scope_filter.is_empty:
        raise NotFoundError("Member not found.")
    args: list[Any] = [UUID(caller.organization_id)]
    allowed = _allowed_members_sql(scope_filter, args)
    if allowed is None:
        return
    if not allowed:
        raise NotFoundError("Member not found.")
    args.append(member_id)
    sql = f"SELECT ${len(args)}::uuid IN ({allowed})"  # nosec B608
    if not await conn.fetchval(sql, *args):
        raise NotFoundError("Member not found.")


class MemberOrgUnit(BaseModel):
    org_unit_id: str
    is_primary: bool
    org_unit_name: str | None = None


class MemberTeam(BaseModel):
    team_id: str
    team_name: str | None = None
    role_in_team: str | None = None


class MemberSummary(BaseModel):
    id: str
    display_name: str
    email: str | None = None
    phone: str | None = None
    status: str
    is_suspended: bool = False


class MemberProfileResponse(BaseModel):
    id: str
    display_name: str
    email: str | None = None
    phone: str | None = None
    status: str
    is_suspended: bool
    org_units: list[MemberOrgUnit]
    teams: list[MemberTeam]


class MemberAccessResponse(BaseModel):
    member_id: str
    permissions: list[dict[str, Any]]


@router.get("", openapi_extra=permission_extra("member.read"))
async def list_members(
    request: Request,
    *,
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    search: str | None = None,
    org_unit_id: UUID | None = None,
    team_id: UUID | None = None,
    status: str | None = None,
    member_ctx: MemberContext = Depends(require_member("member.read")),
    conn: Any = Depends(get_db),
) -> dict[str, Any]:
    scope_filter = default_scope_resolver.resolve_scope_filter(member_ctx, "member.read")
    if scope_filter.is_empty:
        return success_response(data=[], request_id=request_id(request))

    clauses = ["m.organization_id = $1"]
    args: list[Any] = [UUID(member_ctx.organization_id)]

    if search:
        args.append(f"%{search}%")
        clauses.append(f"m.display_name ILIKE ${len(args)}")

    if status:
        args.append(status)
        clauses.append(f"m.status = ${len(args)}")

    if org_unit_id:
        args.append(org_unit_id)
        clauses.append(
            "EXISTS (SELECT 1 FROM public.member_org_units mou "  # nosec B608 # noqa: S608 - bound index
            f"WHERE mou.member_id = m.id AND mou.org_unit_id = ${len(args)})"
        )

    if team_id:
        args.append(team_id)
        clauses.append(
            "EXISTS (SELECT 1 FROM public.team_members tm "  # nosec B608 # noqa: S608 - bound index
            f"WHERE tm.member_id = m.id AND tm.team_id = ${len(args)})"
        )

    allowed = _allowed_members_sql(scope_filter, args)
    if allowed is not None:
        if not allowed:
            return success_response(data=[], request_id=request_id(request))
        clauses.append(f"m.id IN ({allowed})")

    args.append(limit)
    sql = f"""
        SELECT m.id, m.display_name, m.email, m.status
        FROM public.members m
        WHERE {" AND ".join(clauses)}
        ORDER BY m.display_name ASC
        LIMIT ${len(args)}
    """  # nosec B608 # noqa: S608 - clauses are fixed strings, values are bound
    rows = await conn.fetch(sql, *args)
    members = [
        MemberSummary(
            id=str(r["id"]),
            display_name=r["display_name"],
            email=r["email"],
            status=r["status"],
            is_suspended=r["status"] == "suspended",
        )
        for r in rows
    ]
    return success_response(data=[m.model_dump(mode="json") for m in members], request_id=request_id(request))


@router.get(
    "/{member_id}", response_model=MemberProfileResponse, openapi_extra=permission_extra("member.read")
)
async def get_member_profile(
    member_id: UUID,
    member_ctx: MemberContext = Depends(require_member("member.read")),
    conn: Any = Depends(get_db),
) -> MemberProfileResponse:
    await _require_member_in_scope(conn, member_ctx, "member.read", member_id)

    row = await conn.fetchrow(
        "SELECT id, display_name, email, status FROM public.members WHERE id = $1 AND organization_id = $2",
        member_id,
        UUID(member_ctx.organization_id),
    )
    if row is None:
        raise NotFoundError("Member not found.")

    ou_rows = await conn.fetch(
        "SELECT mou.org_unit_id, mou.relation = 'primary' AS is_primary, ou.name AS org_unit_name "
        "FROM public.member_org_units mou "
        "JOIN public.org_units ou ON ou.id = mou.org_unit_id "
        "WHERE mou.member_id = $1 AND mou.organization_id = $2",
        member_id,
        UUID(member_ctx.organization_id),
    )
    team_rows = await conn.fetch(
        "SELECT tm.team_id, tm.team_role AS role_in_team, t.name AS team_name "
        "FROM public.team_members tm "
        "JOIN public.teams t ON t.id = tm.team_id "
        "WHERE tm.member_id = $1 AND tm.organization_id = $2 "
        "AND (tm.valid_to IS NULL OR tm.valid_to > now())",
        member_id,
        UUID(member_ctx.organization_id),
    )

    return MemberProfileResponse(
        id=str(row["id"]),
        display_name=row["display_name"],
        email=row["email"],
        status=row["status"],
        is_suspended=row["status"] == "suspended",
        org_units=[
            MemberOrgUnit(
                org_unit_id=str(r["org_unit_id"]),
                is_primary=r["is_primary"],
                org_unit_name=r["org_unit_name"],
            )
            for r in ou_rows
        ],
        teams=[
            MemberTeam(
                team_id=str(r["team_id"]),
                team_name=r["team_name"],
                role_in_team=r["role_in_team"],
            )
            for r in team_rows
        ],
    )


@router.get(
    "/{member_id}/access",
    response_model=MemberAccessResponse,
    openapi_extra=permission_extra("role_grant.read"),
)
async def get_member_access(
    member_id: UUID,
    member_ctx: MemberContext = Depends(require_member("role_grant.read")),
    conn: Any = Depends(get_db),
) -> MemberAccessResponse:
    await _require_member_in_scope(conn, member_ctx, "role_grant.read", member_id)
    row = await conn.fetchrow(
        "SELECT id, status FROM public.members WHERE id = $1 AND organization_id = $2",
        member_id,
        UUID(member_ctx.organization_id),
    )
    if row is None:
        raise NotFoundError("Member not found.")

    target_context = await load_member_context(
        conn, UUID(member_ctx.organization_id), member_id, is_suspended=row["status"] == "suspended"
    )

    perms = effective_permissions(target_context)
    return MemberAccessResponse(member_id=str(member_id), permissions=perms)
