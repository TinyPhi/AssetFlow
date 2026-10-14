# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Teams API router (§B4.1, §B5.2, §C4.2, M1.4-T4)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, status

from app.api.deps import permission_extra
from app.api.v1.caller import request_id, resolve_caller
from app.core.envelope import success_response
from app.modules.organization.schemas import (
    TeamArchive,
    TeamCreate,
    TeamMemberAdd,
    TeamMemberUpdate,
    TeamUpdate,
)
from app.modules.organization.service import (
    add_team_member,
    archive_team,
    create_team,
    get_team,
    list_team_members,
    list_teams,
    remove_team_member,
    update_team,
    update_team_member,
)

router = APIRouter(prefix="/teams", tags=["teams"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a team",
    openapi_extra=permission_extra("team.create"),
)
async def create_t(request: Request, body: TeamCreate) -> dict[str, Any]:
    """Create a new operational or functional team."""
    org_id, caller = resolve_caller(request)
    req_id = request_id(request)
    pool = request.app.state.pool
    team = await create_team(pool, organization_id=org_id, caller=caller, data=body, request_id=req_id)
    return success_response(data=team.model_dump(mode="json"), request_id=req_id)


@router.get("", summary="List teams", openapi_extra=permission_extra("team.read"))
async def get_t_list(
    request: Request,
    status: str | None = None,
    owning_org_unit_id: UUID | None = None,
) -> dict[str, Any]:
    """List teams within caller scope."""
    org_id, caller = resolve_caller(request)
    req_id = request_id(request)
    pool = request.app.state.pool
    teams = await list_teams(
        pool,
        organization_id=org_id,
        caller=caller,
        status=status,
        owning_org_unit_id=owning_org_unit_id,
    )
    return success_response(data=[t.model_dump(mode="json") for t in teams], request_id=req_id)


@router.get("/{id}", summary="Get a team by ID", openapi_extra=permission_extra("team.read"))
async def get_t(request: Request, id: UUID) -> dict[str, Any]:  # noqa: A002
    """Retrieve details for a specific team."""
    org_id, caller = resolve_caller(request)
    req_id = request_id(request)
    pool = request.app.state.pool
    team = await get_team(pool, organization_id=org_id, caller=caller, team_id=id)
    return success_response(data=team.model_dump(mode="json"), request_id=req_id)


@router.patch("/{id}", summary="Update a team", openapi_extra=permission_extra("team.update"))
@router.put("/{id}", summary="Update a team", openapi_extra=permission_extra("team.update"))
async def update_t(
    request: Request,
    body: TeamUpdate,
    id: UUID,  # noqa: A002
) -> dict[str, Any]:
    """Update name, type, skills, owning unit, or working calendar of a team."""
    org_id, caller = resolve_caller(request)
    req_id = request_id(request)
    pool = request.app.state.pool
    team = await update_team(
        pool, organization_id=org_id, caller=caller, team_id=id, data=body, request_id=req_id
    )
    return success_response(data=team.model_dump(mode="json"), request_id=req_id)


@router.post("/{id}/archive", summary="Archive a team", openapi_extra=permission_extra("team.archive"))
async def archive_t(
    request: Request,
    body: TeamArchive,
    id: UUID,  # noqa: A002
) -> dict[str, Any]:
    """Archive a team if no active member assignments exist."""
    org_id, caller = resolve_caller(request)
    req_id = request_id(request)
    pool = request.app.state.pool
    team = await archive_team(
        pool, organization_id=org_id, caller=caller, team_id=id, data=body, request_id=req_id
    )
    return success_response(data=team.model_dump(mode="json"), request_id=req_id)


# ==============================================================================
# Team Members
# ==============================================================================


@router.get("/{id}/members", summary="List team members", openapi_extra=permission_extra("team.read"))
async def get_members(request: Request, id: UUID) -> dict[str, Any]:  # noqa: A002
    """List members assigned to a team."""
    org_id, caller = resolve_caller(request)
    req_id = request_id(request)
    pool = request.app.state.pool
    members = await list_team_members(pool, organization_id=org_id, caller=caller, team_id=id)
    return success_response(data=[m.model_dump(mode="json") for m in members], request_id=req_id)


@router.post(
    "/{id}/members",
    status_code=status.HTTP_201_CREATED,
    summary="Add a member to a team",
    openapi_extra=permission_extra("team.update"),
)
async def add_member(
    request: Request,
    body: TeamMemberAdd,
    id: UUID,  # noqa: A002
) -> dict[str, Any]:
    """Assign a member to a team with a specific role and validity period."""
    org_id, caller = resolve_caller(request)
    req_id = request_id(request)
    pool = request.app.state.pool
    member = await add_team_member(
        pool, organization_id=org_id, caller=caller, team_id=id, data=body, request_id=req_id
    )
    return success_response(data=member.model_dump(mode="json"), request_id=req_id)


@router.patch(
    "/{id}/members/{member_id}",
    summary="Update a team member assignment",
    openapi_extra=permission_extra("team.update"),
)
@router.put(
    "/{id}/members/{member_id}",
    summary="Update a team member assignment",
    openapi_extra=permission_extra("team.update"),
)
async def update_member(
    request: Request,
    body: TeamMemberUpdate,
    id: UUID,  # noqa: A002
    member_id: UUID,
) -> dict[str, Any]:
    """Update role or expiration date for a member assigned to a team."""
    org_id, caller = resolve_caller(request)
    req_id = request_id(request)
    pool = request.app.state.pool
    member = await update_team_member(
        pool,
        organization_id=org_id,
        caller=caller,
        team_id=id,
        member_id=member_id,
        data=body,
        request_id=req_id,
    )
    return success_response(data=member.model_dump(mode="json"), request_id=req_id)


@router.delete(
    "/{id}/members/{member_id}",
    summary="Remove a member from a team",
    openapi_extra=permission_extra("team.update"),
)
async def remove_member(
    request: Request,
    id: UUID,  # noqa: A002
    member_id: UUID,
) -> dict[str, Any]:
    """Remove a member assignment from a team."""
    org_id, caller = resolve_caller(request)
    req_id = request_id(request)
    pool = request.app.state.pool
    await remove_team_member(
        pool,
        organization_id=org_id,
        caller=caller,
        team_id=id,
        member_id=member_id,
        request_id=req_id,
    )
    return success_response(data={"removed": True}, request_id=req_id)
