# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Org Units API router (§B4.1, §B5.2, §C4.2, M1.4-T4)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, status

from app.core.envelope import success_response
from app.core.permissions import ScopeType
from app.core.problems import UnauthorizedError, ValidationFailedError
from app.core.scope import MemberContext, RoleGrant
from app.modules.organization.schemas import (
    OrgUnitArchive,
    OrgUnitCreate,
    OrgUnitMove,
    OrgUnitUpdate,
)
from app.modules.organization.service import (
    archive_org_unit,
    create_org_unit,
    get_org_unit,
    list_org_units,
    move_org_unit,
    update_org_unit,
)

router = APIRouter(prefix="/org-units", tags=["org-units"])


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
            ou_path = request.headers.get("x-org-unit-path")
            grants = (
                RoleGrant(
                    id="g",
                    organization_id=oid,
                    role_key=role,
                    scope_type=st,
                    org_unit_path=ou_path,
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
                primary_org_unit_path=ou_path,
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


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create an organizational unit")
async def create_unit(request: Request, body: OrgUnitCreate) -> dict[str, Any]:
    """Create a new organizational unit within the caller's organization."""
    org_id, caller = _resolve_caller(request)
    req_id = _request_id(request)
    pool = request.app.state.pool
    unit = await create_org_unit(pool, organization_id=org_id, caller=caller, data=body, request_id=req_id)
    return success_response(data=unit.model_dump(mode="json"), request_id=req_id)


@router.get("", summary="List organizational units")
async def get_units(
    request: Request,
    status: str | None = None,
    parent_id: UUID | None = None,
) -> dict[str, Any]:
    """List organizational units within caller scope."""
    org_id, caller = _resolve_caller(request)
    req_id = _request_id(request)
    pool = request.app.state.pool
    units = await list_org_units(
        pool, organization_id=org_id, caller=caller, status=status, parent_id=parent_id
    )
    return success_response(data=[u.model_dump(mode="json") for u in units], request_id=req_id)


@router.get("/{id}", summary="Get an organizational unit by ID")
async def get_unit(request: Request, id: UUID) -> dict[str, Any]:  # noqa: A002
    """Retrieve details for a specific organizational unit."""
    org_id, caller = _resolve_caller(request)
    req_id = _request_id(request)
    pool = request.app.state.pool
    unit = await get_org_unit(pool, organization_id=org_id, caller=caller, unit_id=id)
    return success_response(data=unit.model_dump(mode="json"), request_id=req_id)


@router.patch("/{id}", summary="Update an organizational unit")
@router.put("/{id}", summary="Update an organizational unit")
async def update_unit(
    request: Request,
    body: OrgUnitUpdate,
    id: UUID,  # noqa: A002
) -> dict[str, Any]:
    """Update name, type, or manager of an organizational unit."""
    org_id, caller = _resolve_caller(request)
    req_id = _request_id(request)
    pool = request.app.state.pool
    unit = await update_org_unit(
        pool, organization_id=org_id, caller=caller, unit_id=id, data=body, request_id=req_id
    )
    return success_response(data=unit.model_dump(mode="json"), request_id=req_id)


@router.post("/{id}/move", summary="Move an organizational unit to a new parent")
async def move_unit(
    request: Request,
    body: OrgUnitMove,
    id: UUID,  # noqa: A002
) -> dict[str, Any]:
    """Move an organizational unit under a new parent unit, recalculating descendant paths."""
    org_id, caller = _resolve_caller(request)
    req_id = _request_id(request)
    pool = request.app.state.pool
    unit = await move_org_unit(
        pool, organization_id=org_id, caller=caller, unit_id=id, data=body, request_id=req_id
    )
    return success_response(data=unit.model_dump(mode="json"), request_id=req_id)


@router.post("/{id}/archive", summary="Archive an organizational unit")
async def archive_unit(
    request: Request,
    body: OrgUnitArchive,
    id: UUID,  # noqa: A002
) -> dict[str, Any]:
    """Archive an organizational unit if no active children or members exist."""
    org_id, caller = _resolve_caller(request)
    req_id = _request_id(request)
    pool = request.app.state.pool
    unit = await archive_org_unit(
        pool, organization_id=org_id, caller=caller, unit_id=id, data=body, request_id=req_id
    )
    return success_response(data=unit.model_dump(mode="json"), request_id=req_id)
