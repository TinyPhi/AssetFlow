# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Members and access view endpoints (§B5.8, M1.6-T4)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.api.deps import get_db, permission_extra, require_member
from app.api.v1.caller import request_id
from app.core.envelope import success_response
from app.core.problems import NotFoundError, ProblemError
from app.core.scope import MemberContext, default_scope_resolver
from app.modules.organization.profile import effective_permissions

router = APIRouter(prefix="/members", tags=["Members"])


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
        clauses.append(f"EXISTS (SELECT 1 FROM public.member_org_units mou WHERE mou.member_id = m.id AND mou.org_unit_id = ${len(args)})")

    if team_id:
        args.append(team_id)
        clauses.append(f"EXISTS (SELECT 1 FROM public.team_members tm WHERE tm.member_id = m.id AND tm.team_id = ${len(args)})")

    args.append(limit)
    sql = f"""
        SELECT m.id, m.display_name, m.email, m.status
        FROM public.members m
        WHERE {' AND '.join(clauses)}
        ORDER BY m.display_name ASC
        LIMIT ${len(args)}
    """
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


@router.get("/{member_id}", response_model=MemberProfileResponse, openapi_extra=permission_extra("member.read"))
async def get_member_profile(
    member_id: UUID,
    member_ctx: MemberContext = Depends(require_member("member.read")),
    conn: Any = Depends(get_db),
) -> MemberProfileResponse:
    scope_filter = default_scope_resolver.resolve_scope_filter(member_ctx, "member.read")
    if scope_filter.is_empty:
        raise NotFoundError("Member not found.")

    row = await conn.fetchrow(
        "SELECT id, display_name, email, phone, status, is_suspended FROM public.members "
        "WHERE id = $1 AND organization_id = $2",
        member_id,
        UUID(member_ctx.organization_id),
    )
    if row is None:
        raise NotFoundError("Member not found.")

    ou_rows = await conn.fetch(
        "SELECT mou.org_unit_id, mou.is_primary, ou.name AS org_unit_name "
        "FROM public.member_org_units mou "
        "JOIN public.org_units ou ON ou.id = mou.org_unit_id "
        "WHERE mou.member_id = $1",
        member_id,
    )
    team_rows = await conn.fetch(
        "SELECT tm.team_id, tm.role_in_team, t.name AS team_name "
        "FROM public.team_members tm "
        "JOIN public.teams t ON t.id = tm.team_id "
        "WHERE tm.member_id = $1",
        member_id,
    )

    return MemberProfileResponse(
        id=str(row["id"]),
        display_name=row["display_name"],
        email=row["email"],
        phone=row["phone"],
        status=row["status"],
        is_suspended=row["is_suspended"],
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


@router.get("/{member_id}/access", response_model=MemberAccessResponse, openapi_extra=permission_extra("role_grant.read"))
async def get_member_access(
    member_id: UUID,
    member_ctx: MemberContext = Depends(require_member("role_grant.read")),
    conn: Any = Depends(get_db),
) -> MemberAccessResponse:
    row = await conn.fetchrow(
        "SELECT id, is_suspended FROM public.members WHERE id = $1 AND organization_id = $2",
        member_id,
        UUID(member_ctx.organization_id),
    )
    if row is None:
        raise NotFoundError("Member not found.")

    # Query grants for target member to compute access via ScopeResolver
    grants_rows = await conn.fetch(
        "SELECT role, scope_type, scope_id FROM public.role_grants WHERE member_id = $1",
        member_id,
    )
    from app.core.scope import RoleGrant, ScopeType

    grants: list[RoleGrant] = []
    for gr in grants_rows:
        grants.append(
            RoleGrant(
                id=str(gr.get("id", "g")),
                organization_id=member_ctx.organization_id,
                role_key=gr.get("role") or gr.get("role_key", "member"),
                scope_type=ScopeType(gr["scope_type"]) if gr.get("scope_type") in ScopeType else ScopeType.ORGANIZATION,
                scope_id=str(gr["scope_id"]) if gr.get("scope_id") else None,
            )
        )

    target_context = MemberContext(
        member_id=str(member_id),
        organization_id=member_ctx.organization_id,
        is_suspended=row["is_suspended"],
        grants=grants,
    )

    perms = effective_permissions(target_context)
    return MemberAccessResponse(member_id=str(member_id), permissions=perms)
