# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Asset API: create, edit, detail, list (§B8.1, M2.1-T5, P8-07). Later part adds saved views.
Every route needs the `assets` module installed."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse

from app.core.envelope import success_response
from app.core.openapi_meta import permission_extra
from app.core.permissions import ScopeType
from app.core.problems import FieldError, UnauthorizedError, ValidationFailedError
from app.core.scope import MemberContext, RoleGrant
from app.modules.assets import repository as repo
from app.modules.assets import service
from app.modules.assets.permissions import CREATE_PERMISSION, READ_PERMISSION, UPDATE_PERMISSION
from app.modules.assets.schemas import AssetCreate, AssetListItem, AssetStatusChange, AssetUpdate
from app.modules.organization.modules import require_module

_CUSTOM_FIELD_OPS = ("gte", "lte")

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


def _custom_field_filters(request: Request) -> tuple[tuple[str, str, str], ...]:
    """Parse `cf.<key>`, `cf.<key>.gte` and `cf.<key>.lte` query parameters (§B8.1).

    FastAPI has no declared parameter for an open-ended `cf.*` family, so these are read directly
    off `request.query_params`; every other query parameter below is still a normal, validated
    FastAPI parameter (§C4.4: no filter ever reaches SQL as raw user text without a check first).
    """
    out: list[tuple[str, str, str]] = []
    for name, value in request.query_params.multi_items():
        if not name.startswith("cf."):
            continue
        rest = name.removeprefix("cf.")
        key, _, op = rest.rpartition(".")
        if key and op in _CUSTOM_FIELD_OPS:
            out.append((key, op, value))
        else:
            out.append((rest, "eq", value))
    return tuple(out)


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


@router.get(
    "/vocabulary",
    summary="The organization's status labels and criticality levels",
    openapi_extra=permission_extra(READ_PERMISSION),
)
async def get_vocabulary_route(request: Request) -> dict[str, Any]:
    member = _resolve_member(request)
    vocabulary = await service.get_vocabulary(
        request.app.state.pool, organization_id=UUID(member.organization_id), caller=member
    )
    return success_response(data=vocabulary.model_dump(mode="json"), request_id=_request_id(request))


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


@router.get("", summary="List assets", openapi_extra=permission_extra(READ_PERMISSION))
async def list_assets_route(
    request: Request,
    *,
    q: str | None = None,
    status: list[str] | None = Query(default=None),  # noqa: B008 - FastAPI's own query idiom
    status_category: str | None = None,
    category_id: UUID | None = None,
    include_subcategories: bool = False,
    owner_org_unit_id: UUID | None = None,
    include_sub_units: bool = False,
    location_id: UUID | None = None,
    include_sub_locations: bool = False,
    holder_type: Literal["member", "team", "location"] | None = None,
    holder_member_id: UUID | None = None,
    holder_team_id: UUID | None = None,
    criticality: list[str] | None = Query(default=None),  # noqa: B008 - FastAPI's own query idiom
    manufacturer_id: UUID | None = None,
    supplier_id: UUID | None = None,
    warranty_end_before: date | None = None,
    warranty_end_after: date | None = None,
    purchase_date_before: date | None = None,
    purchase_date_after: date | None = None,
    updated_since: datetime | None = None,
    sort: str = "-created_at",
    after: str | None = None,
    limit: int = 50,
    include_total: bool = False,
    fields: str | None = None,
) -> dict[str, Any]:
    member = _resolve_member(request)
    selected = _parse_fields(fields)
    pool = request.app.state.pool
    query = repo.AssetQuery(
        q=q,
        status=tuple(status) if status else (),
        category_id=category_id,
        include_subcategories=include_subcategories,
        owner_org_unit_id=owner_org_unit_id,
        include_sub_units=include_sub_units,
        location_id=location_id,
        include_sub_locations=include_sub_locations,
        holder_type=holder_type,
        holder_member_id=holder_member_id,
        holder_team_id=holder_team_id,
        criticality=tuple(criticality) if criticality else (),
        manufacturer_id=manufacturer_id,
        supplier_id=supplier_id,
        warranty_end_before=warranty_end_before,
        warranty_end_after=warranty_end_after,
        purchase_date_before=purchase_date_before,
        purchase_date_after=purchase_date_after,
        updated_since=updated_since,
    )
    result = await service.list_assets(
        pool,
        organization_id=UUID(member.organization_id),
        caller=member,
        query=query,
        custom_field_filters=_custom_field_filters(request),
        status_category=status_category,
        sort=sort,
        after=after,
        limit=limit,
        include_total=include_total,
    )
    data = {
        "items": [_render_list_item(item, selected) for item in result.items],
        "next_cursor": result.next_cursor,
        "total": result.total,
    }
    return success_response(data=data, request_id=_request_id(request))


#: `fields` allowlist: the list item's own fields (§B4.5); `id` is always returned.
_LIST_FIELDS = frozenset(AssetListItem.model_fields) - {"id"}


def _parse_fields(fields: str | None) -> frozenset[str] | None:
    if not fields:
        return None
    wanted = frozenset(f.strip() for f in fields.split(",") if f.strip())
    unknown = sorted(wanted - _LIST_FIELDS)
    if unknown:
        raise ValidationFailedError(
            errors=[FieldError(field="query.fields", message=f"unknown field(s): {', '.join(unknown)}")]
        )
    return wanted


def _render_list_item(item: dict[str, Any], selected: frozenset[str] | None) -> dict[str, Any]:
    full = AssetListItem.model_validate(item).model_dump(mode="json")
    if selected is None:
        return full
    return {k: v for k, v in full.items() if k == "id" or k in selected}


@router.post(
    "/{asset_id}/change-status",
    summary="Change an asset's status along the domain template's transitions",
    openapi_extra=permission_extra(UPDATE_PERMISSION),
)
async def change_status_route(request: Request, asset_id: UUID, body: AssetStatusChange) -> dict[str, Any]:
    member = _resolve_member(request)
    asset = await service.change_status(
        request.app.state.pool,
        organization_id=UUID(member.organization_id),
        caller=member,
        secrets_provider=_secrets_provider(request),
        asset_id=asset_id,
        to_status=body.to_status,
        version=body.version,
        reason=body.reason,
        request_id=_request_id(request),
    )
    return success_response(data=asset.model_dump(mode="json"), request_id=_request_id(request))


@router.get(
    "/{asset_id}/transitions",
    summary="The status changes the caller may take now",
    openapi_extra=permission_extra(READ_PERMISSION),
)
async def list_transitions_route(request: Request, asset_id: UUID) -> dict[str, Any]:
    member = _resolve_member(request)
    items = await service.list_transitions(
        request.app.state.pool,
        organization_id=UUID(member.organization_id),
        caller=member,
        asset_id=asset_id,
    )
    return success_response(
        data={"items": [item.model_dump(mode="json") for item in items]}, request_id=_request_id(request)
    )
