# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Asset API: create, edit, detail (§B8.1, M2.1-T5, P8-07). Later parts add list/saved-views here.
Every route needs the `assets` module installed."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from app.api.deps import permission_extra, require_module
from app.core.envelope import success_response
from app.core.permissions import ScopeType
from app.core.problems import UnauthorizedError
from app.core.scope import MemberContext, RoleGrant
from app.modules.assets import service
from app.modules.assets.permissions import CREATE_PERMISSION, READ_PERMISSION, UPDATE_PERMISSION
from app.modules.assets.schemas import AssetCreate, AssetUpdate

router = APIRouter(prefix="/assets", tags=["assets"], dependencies=[Depends(require_module("assets"))])


def _resolve_member(request: Request) -> MemberContext:
    """Same shape as `app.modules.assets.catalog.router._resolve_member`: prefers
    `AuthMiddleware`'s `request.state.member`, with a header shortcut (including scope type, org
    unit path and team ids) for tests that do not run a full sign-in."""
    member: MemberContext | None = getattr(request.state, "member", None)
    if member is None:
        mid, oid = request.headers.get("x-member-id"), request.headers.get("x-organization-id")
        if mid and oid:
            role = request.headers.get("x-role", "admin")
            st_raw = request.headers.get("x-scope-type", "organization")
            scope_type = ScopeType(st_raw) if st_raw in ScopeType else ScopeType.ORGANIZATION
            org_unit_path = request.headers.get("x-org-unit-path")
            team_ids = (
                tuple(request.headers.get("x-team-ids", "").split(","))
                if request.headers.get("x-team-ids")
                else ()
            )
            grants = (
                RoleGrant(
                    id="g",
                    organization_id=oid,
                    role_key=role,
                    scope_type=scope_type,
                    org_unit_path=org_unit_path,
                    scope_id=request.headers.get("x-scope-id"),
                ),
            )
            member = MemberContext(
                member_id=mid,
                organization_id=oid,
                grants=grants,
                team_ids=team_ids,
                primary_org_unit_path=org_unit_path,
            )
    if member is None:
        raise UnauthorizedError()
    return member


def _request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", "")
    return value if isinstance(value, str) else ""


def _secrets_provider(request: Request) -> Any:
    return request.app.state.registry.secrets


@router.post(
    "", status_code=201, summary="Create an asset", openapi_extra=permission_extra(CREATE_PERMISSION)
)
async def create_asset_route(request: Request, body: AssetCreate) -> dict[str, Any]:
    member = _resolve_member(request)
    pool = request.app.state.pool
    asset = await service.create_asset(
        pool,
        organization_id=UUID(member.organization_id),
        caller=member,
        secrets_provider=_secrets_provider(request),
        data=body,
        request_id=_request_id(request),
        idempotency_key=request.headers.get("idempotency-key"),
    )
    return success_response(
        data=asset.model_dump(mode="json"), request_id=_request_id(request), status_code=201
    )


@router.patch("/{asset_id}", summary="Edit an asset", openapi_extra=permission_extra(UPDATE_PERMISSION))
async def update_asset_route(request: Request, asset_id: UUID, body: AssetUpdate) -> dict[str, Any]:
    member = _resolve_member(request)
    pool = request.app.state.pool
    asset = await service.update_asset(
        pool,
        organization_id=UUID(member.organization_id),
        caller=member,
        secrets_provider=_secrets_provider(request),
        asset_id=asset_id,
        data=body,
        request_id=_request_id(request),
    )
    return success_response(data=asset.model_dump(mode="json"), request_id=_request_id(request))


@router.get("/{asset_id}", summary="Get an asset", openapi_extra=permission_extra(READ_PERMISSION))
async def get_asset_route(request: Request, asset_id: UUID) -> Response:
    member = _resolve_member(request)
    pool = request.app.state.pool
    asset = await service.get_asset(
        pool,
        organization_id=UUID(member.organization_id),
        caller=member,
        secrets_provider=_secrets_provider(request),
        asset_id=asset_id,
    )
    etag = f'"{asset.version}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    body = success_response(data=asset.model_dump(mode="json"), request_id=_request_id(request))
    return JSONResponse(body, headers={"ETag": etag})
