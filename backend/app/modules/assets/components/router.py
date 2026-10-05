# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Component routes: list, attach, detach (§B8.1, M2.1-T6, P8-09). Needs the `assets` module."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.api.deps import permission_extra, require_module
from app.core.envelope import success_response
from app.modules.assets.components import service
from app.modules.assets.components.schemas import (
    ComponentAttach,
    ComponentChildRead,
    ComponentDetach,
    ComponentLinkRead,
)
from app.modules.assets.permissions import READ_PERMISSION, UPDATE_PERMISSION
from app.modules.assets.router import _request_id, _resolve_member

router = APIRouter(
    prefix="/assets/{asset_id}/components",
    tags=["assets"],
    dependencies=[Depends(require_module("assets"))],
)


@router.get("", summary="List an asset's components", openapi_extra=permission_extra(READ_PERMISSION))
async def list_components_route(
    request: Request, asset_id: UUID, include_history: bool = False
) -> dict[str, Any]:
    member = _resolve_member(request)
    rows = await service.list_components(
        request.app.state.pool,
        organization_id=UUID(member.organization_id),
        caller=member,
        asset_id=asset_id,
        include_history=include_history,
    )
    items = [ComponentChildRead.model_validate(row).model_dump(mode="json") for row in rows]
    return success_response(data={"items": items}, request_id=_request_id(request))


@router.post(
    "",
    status_code=201,
    summary="Attach a child asset",
    openapi_extra=permission_extra(UPDATE_PERMISSION),
)
async def attach_component_route(request: Request, asset_id: UUID, body: ComponentAttach) -> dict[str, Any]:
    member = _resolve_member(request)
    link = await service.attach_component(
        request.app.state.pool,
        organization_id=UUID(member.organization_id),
        caller=member,
        parent_asset_id=asset_id,
        data=body,
        request_id=_request_id(request),
    )
    return success_response(
        data=ComponentLinkRead.model_validate(link).model_dump(mode="json"),
        request_id=_request_id(request),
        status_code=201,
    )


@router.post(
    "/{child_asset_id}/detach",
    summary="Detach a child asset",
    openapi_extra=permission_extra(UPDATE_PERMISSION),
)
async def detach_component_route(
    request: Request, asset_id: UUID, child_asset_id: UUID, body: ComponentDetach
) -> dict[str, Any]:
    member = _resolve_member(request)
    link = await service.detach_component(
        request.app.state.pool,
        organization_id=UUID(member.organization_id),
        caller=member,
        parent_asset_id=asset_id,
        child_asset_id=child_asset_id,
        data=body,
        request_id=_request_id(request),
    )
    return success_response(
        data=ComponentLinkRead.model_validate(link).model_dump(mode="json"), request_id=_request_id(request)
    )
