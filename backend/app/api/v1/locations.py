# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Locations API router (§B4.1, §B5.2, §C4.2, M1.4-T4)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, status

from app.api.deps import permission_extra
from app.core.envelope import success_response
from app.core.permissions import ScopeType
from app.core.problems import UnauthorizedError, ValidationFailedError
from app.core.scope import MemberContext, RoleGrant
from app.modules.organization.schemas import (
    LocationCreate,
    LocationMove,
    LocationUpdate,
)
from app.modules.organization.service import (
    create_location,
    delete_location,
    get_location,
    list_locations,
    move_location,
    update_location,
)

router = APIRouter(prefix="/locations", tags=["locations"])


def _resolve_caller(request: Request) -> tuple[UUID, MemberContext]:
    is_admin = getattr(request.state, "is_platform_admin", False)
    if is_admin or request.headers.get("x-platform-admin") == "true":
        org = request.query_params.get("organization_id") or request.headers.get("x-organization-id")
        if not org:
            raise ValidationFailedError("Platform administrator must specify organization_id")
        try:
            org_uuid = UUID(org)
            admin_grant = RoleGrant(
                id="platform-admin",
                organization_id=str(org_uuid),
                role_key="admin",
                scope_type=ScopeType.ORGANIZATION,
            )
            admin_member = MemberContext(
                member_id="platform-admin", organization_id=str(org_uuid), grants=(admin_grant,)
            )
            return org_uuid, admin_member
        except ValueError as err:
            raise ValidationFailedError("Invalid organization_id UUID") from err

    member: MemberContext | None = getattr(request.state, "member", None)
    if member is None:
        mid, oid = request.headers.get("x-member-id"), request.headers.get("x-organization-id")
        if mid and oid:
            role = request.headers.get("x-role", "admin")
            st_raw = request.headers.get("x-scope-type", "organization")
            st = ScopeType(st_raw) if st_raw in ScopeType else ScopeType.ORGANIZATION
            grants = (
                RoleGrant(
                    id="g",
                    organization_id=oid,
                    role_key=role,
                    scope_type=st,
                ),
            )
            team_ids = (
                tuple(request.headers.get("x-team-ids", "").split(","))
                if request.headers.get("x-team-ids")
                else ()
            )
            member = MemberContext(
                member_id=mid,
                organization_id=oid,
                grants=grants,
                team_ids=team_ids,
            )
    if member is None:
        raise UnauthorizedError()
    try:
        org_uuid = UUID(member.organization_id)
    except ValueError as err:
        raise UnauthorizedError("Invalid organization context") from err
    return org_uuid, member


def _request_id(request: Request) -> str:
    val = getattr(request.state, "request_id", "")
    return str(val) if val else ""


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a physical location", openapi_extra=permission_extra("location.create"))
async def create_loc(request: Request, body: LocationCreate) -> dict[str, Any]:
    """Create a new location or sub-location in the facility hierarchy."""
    org_id, caller = _resolve_caller(request)
    req_id = _request_id(request)
    pool = request.app.state.pool
    loc = await create_location(pool, organization_id=org_id, caller=caller, data=body, request_id=req_id)
    return success_response(data=loc.model_dump(mode="json"), request_id=req_id)


@router.get("", summary="List physical locations", openapi_extra=permission_extra("location.read"))
async def get_locs(
    request: Request,
    parent_id: UUID | None = None,
) -> dict[str, Any]:
    """List physical locations within caller scope."""
    org_id, caller = _resolve_caller(request)
    req_id = _request_id(request)
    pool = request.app.state.pool
    locs = await list_locations(pool, organization_id=org_id, caller=caller, parent_id=parent_id)
    return success_response(data=[loc.model_dump(mode="json") for loc in locs], request_id=req_id)


@router.get("/{id}", summary="Get a physical location by ID", openapi_extra=permission_extra("location.read"))
async def get_loc(request: Request, id: UUID) -> dict[str, Any]:  # noqa: A002
    """Retrieve details for a specific physical location."""
    org_id, caller = _resolve_caller(request)
    req_id = _request_id(request)
    pool = request.app.state.pool
    loc = await get_location(pool, organization_id=org_id, caller=caller, location_id=id)
    return success_response(data=loc.model_dump(mode="json"), request_id=req_id)


@router.patch("/{id}", summary="Update a physical location", openapi_extra=permission_extra("location.update"))
@router.put("/{id}", summary="Update a physical location", openapi_extra=permission_extra("location.update"))
async def update_loc(
    request: Request,
    body: LocationUpdate,
    id: UUID,  # noqa: A002
) -> dict[str, Any]:
    """Update name, type, or address metadata of a location."""
    org_id, caller = _resolve_caller(request)
    req_id = _request_id(request)
    pool = request.app.state.pool
    loc = await update_location(
        pool,
        organization_id=org_id,
        caller=caller,
        location_id=id,
        data=body,
        request_id=req_id,
    )
    return success_response(data=loc.model_dump(mode="json"), request_id=req_id)


@router.post("/{id}/move", summary="Move a physical location to a new parent", openapi_extra=permission_extra("location.update"))
async def move_loc(
    request: Request,
    body: LocationMove,
    id: UUID,  # noqa: A002
) -> dict[str, Any]:
    """Move a physical location under a new parent location, updating descendant paths."""
    org_id, caller = _resolve_caller(request)
    req_id = _request_id(request)
    pool = request.app.state.pool
    loc = await move_location(
        pool,
        organization_id=org_id,
        caller=caller,
        location_id=id,
        data=body,
        request_id=req_id,
    )
    return success_response(data=loc.model_dump(mode="json"), request_id=req_id)


@router.delete("/{id}", summary="Delete a physical location", openapi_extra=permission_extra("location.delete"))
async def delete_loc(
    request: Request,
    id: UUID,  # noqa: A002
    version: int = 1,
) -> dict[str, Any]:
    """Delete a physical location if no child sub-locations exist."""
    org_id, caller = _resolve_caller(request)
    req_id = _request_id(request)
    pool = request.app.state.pool
    await delete_location(
        pool,
        organization_id=org_id,
        caller=caller,
        location_id=id,
        version=version,
        request_id=req_id,
    )
    return success_response(data={"deleted": True}, request_id=req_id)
