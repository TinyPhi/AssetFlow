# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Locations API router (§B4.1, §B5.2, §C4.2, M1.4-T4)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, status

from app.api.deps import permission_extra
from app.api.v1.caller import request_id, resolve_caller
from app.core.envelope import success_response
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


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a physical location",
    openapi_extra=permission_extra("location.create"),
)
async def create_loc(request: Request, body: LocationCreate) -> dict[str, Any]:
    """Create a new location or sub-location in the facility hierarchy."""
    org_id, caller = resolve_caller(request)
    req_id = request_id(request)
    pool = request.app.state.pool
    loc = await create_location(pool, organization_id=org_id, caller=caller, data=body, request_id=req_id)
    return success_response(data=loc.model_dump(mode="json"), request_id=req_id)


@router.get("", summary="List physical locations", openapi_extra=permission_extra("location.read"))
async def get_locs(
    request: Request,
    parent_id: UUID | None = None,
) -> dict[str, Any]:
    """List physical locations within caller scope."""
    org_id, caller = resolve_caller(request)
    req_id = request_id(request)
    pool = request.app.state.pool
    locs = await list_locations(pool, organization_id=org_id, caller=caller, parent_id=parent_id)
    return success_response(data=[loc.model_dump(mode="json") for loc in locs], request_id=req_id)


@router.get("/{id}", summary="Get a physical location by ID", openapi_extra=permission_extra("location.read"))
async def get_loc(request: Request, id: UUID) -> dict[str, Any]:  # noqa: A002
    """Retrieve details for a specific physical location."""
    org_id, caller = resolve_caller(request)
    req_id = request_id(request)
    pool = request.app.state.pool
    loc = await get_location(pool, organization_id=org_id, caller=caller, location_id=id)
    return success_response(data=loc.model_dump(mode="json"), request_id=req_id)


@router.patch(
    "/{id}", summary="Update a physical location", openapi_extra=permission_extra("location.update")
)
@router.put("/{id}", summary="Update a physical location", openapi_extra=permission_extra("location.update"))
async def update_loc(
    request: Request,
    body: LocationUpdate,
    id: UUID,  # noqa: A002
) -> dict[str, Any]:
    """Update name, type, or address metadata of a location."""
    org_id, caller = resolve_caller(request)
    req_id = request_id(request)
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


@router.post(
    "/{id}/move",
    summary="Move a physical location to a new parent",
    openapi_extra=permission_extra("location.update"),
)
async def move_loc(
    request: Request,
    body: LocationMove,
    id: UUID,  # noqa: A002
) -> dict[str, Any]:
    """Move a physical location under a new parent location, updating descendant paths."""
    org_id, caller = resolve_caller(request)
    req_id = request_id(request)
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


@router.delete(
    "/{id}", summary="Delete a physical location", openapi_extra=permission_extra("location.delete")
)
async def delete_loc(
    request: Request,
    id: UUID,  # noqa: A002
    version: int = 1,
) -> dict[str, Any]:
    """Delete a physical location if no child sub-locations exist."""
    org_id, caller = resolve_caller(request)
    req_id = request_id(request)
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
