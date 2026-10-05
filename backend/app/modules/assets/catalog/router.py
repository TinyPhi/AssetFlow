# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Catalog reference-data API: categories, custom field definitions, manufacturers, suppliers
(§B8.1, M2.1-T1/T2, P8-06). Every route needs the `assets` module installed; writes need
`asset.update` at organization scope, reads need `asset.read` at any scope (see `service.py`)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.api.deps import permission_extra, require_module
from app.core.envelope import success_response
from app.core.permissions import ScopeType
from app.core.problems import UnauthorizedError
from app.core.scope import MemberContext, RoleGrant
from app.modules.assets.catalog import service
from app.modules.assets.catalog.schemas import (
    CategoryArchive,
    CategoryCreate,
    CategoryMove,
    CategoryUpdate,
    CustomFieldDefinitionArchive,
    CustomFieldDefinitionCreate,
    CustomFieldDefinitionUpdate,
    ManufacturerArchive,
    ManufacturerCreate,
    ManufacturerUpdate,
    SupplierArchive,
    SupplierCreate,
    SupplierUpdate,
)

READ_PERMISSION = service.READ_PERMISSION
WRITE_PERMISSION = service.WRITE_PERMISSION

router = APIRouter(dependencies=[Depends(require_module("assets"))])


def _resolve_member(request: Request) -> MemberContext:
    """Prefer `AuthMiddleware`'s `request.state.member`; a header shortcut remains for tests that
    do not run a full sign-in (mirrors `app.api.v1.org_settings._resolve_member`)."""
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


def _page(request: Request, result: service.CursorPage) -> dict[str, Any]:
    data = {"items": result.items, "next_cursor": result.next_cursor}
    return success_response(data=data, request_id=_request_id(request))


# ==============================================================================
# Asset categories
# ==============================================================================

categories_router = APIRouter(prefix="/asset-categories", tags=["asset-categories"])


@categories_router.get("", summary="List asset categories", openapi_extra=permission_extra(READ_PERMISSION))
async def list_categories_route(
    request: Request,
    status: str | None = None,
    parent_id: UUID | None = None,
    after: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    member = _resolve_member(request)
    pool = request.app.state.pool
    result = await service.list_categories(
        pool,
        organization_id=UUID(member.organization_id),
        caller=member,
        status=status,
        parent_id=parent_id,
        after=after,
        limit=limit,
    )
    return _page(request, result)


@categories_router.post(
    "", status_code=201, summary="Create an asset category", openapi_extra=permission_extra(WRITE_PERMISSION)
)
async def create_category_route(request: Request, body: CategoryCreate) -> dict[str, Any]:
    member = _resolve_member(request)
    pool = request.app.state.pool
    category = await service.create_category(
        pool,
        organization_id=UUID(member.organization_id),
        caller=member,
        data=body,
        request_id=_request_id(request),
    )
    return success_response(
        data=category.model_dump(mode="json"), request_id=_request_id(request), status_code=201
    )


@categories_router.get(
    "/{category_id}", summary="Get an asset category", openapi_extra=permission_extra(READ_PERMISSION)
)
async def get_category_route(request: Request, category_id: UUID) -> dict[str, Any]:
    member = _resolve_member(request)
    pool = request.app.state.pool
    category = await service.get_category(
        pool, organization_id=UUID(member.organization_id), caller=member, category_id=category_id
    )
    return success_response(data=category.model_dump(mode="json"), request_id=_request_id(request))


@categories_router.patch(
    "/{category_id}", summary="Update an asset category", openapi_extra=permission_extra(WRITE_PERMISSION)
)
async def update_category_route(request: Request, category_id: UUID, body: CategoryUpdate) -> dict[str, Any]:
    member = _resolve_member(request)
    pool = request.app.state.pool
    category = await service.update_category(
        pool,
        organization_id=UUID(member.organization_id),
        caller=member,
        category_id=category_id,
        data=body,
        request_id=_request_id(request),
    )
    return success_response(data=category.model_dump(mode="json"), request_id=_request_id(request))


@categories_router.post(
    "/{category_id}/move", summary="Move an asset category", openapi_extra=permission_extra(WRITE_PERMISSION)
)
async def move_category_route(request: Request, category_id: UUID, body: CategoryMove) -> dict[str, Any]:
    member = _resolve_member(request)
    pool = request.app.state.pool
    category = await service.move_category(
        pool,
        organization_id=UUID(member.organization_id),
        caller=member,
        category_id=category_id,
        data=body,
        request_id=_request_id(request),
    )
    return success_response(data=category.model_dump(mode="json"), request_id=_request_id(request))


@categories_router.post(
    "/{category_id}/archive",
    summary="Archive an asset category",
    openapi_extra=permission_extra(WRITE_PERMISSION),
)
async def archive_category_route(
    request: Request, category_id: UUID, body: CategoryArchive
) -> dict[str, Any]:
    member = _resolve_member(request)
    pool = request.app.state.pool
    category = await service.archive_category(
        pool,
        organization_id=UUID(member.organization_id),
        caller=member,
        category_id=category_id,
        data=body,
        request_id=_request_id(request),
    )
    return success_response(data=category.model_dump(mode="json"), request_id=_request_id(request))


# ==============================================================================
# Custom field definitions (nested under a category)
# ==============================================================================


@categories_router.get(
    "/{category_id}/custom-fields",
    summary="List a category's custom field definitions",
    openapi_extra=permission_extra(READ_PERMISSION),
)
async def list_custom_fields_route(
    request: Request, category_id: UUID, status: str | None = None, after: str | None = None, limit: int = 50
) -> dict[str, Any]:
    member = _resolve_member(request)
    pool = request.app.state.pool
    result = await service.list_custom_field_definitions(
        pool,
        organization_id=UUID(member.organization_id),
        caller=member,
        category_id=category_id,
        status=status,
        after=after,
        limit=limit,
    )
    return _page(request, result)


@categories_router.post(
    "/{category_id}/custom-fields",
    status_code=201,
    summary="Define a custom field on a category",
    openapi_extra=permission_extra(WRITE_PERMISSION),
)
async def create_custom_field_route(
    request: Request, category_id: UUID, body: CustomFieldDefinitionCreate
) -> dict[str, Any]:
    member = _resolve_member(request)
    pool = request.app.state.pool
    field = await service.create_custom_field_definition(
        pool,
        organization_id=UUID(member.organization_id),
        caller=member,
        category_id=category_id,
        data=body,
        request_id=_request_id(request),
    )
    return success_response(
        data=field.model_dump(mode="json"), request_id=_request_id(request), status_code=201
    )


@categories_router.get(
    "/{category_id}/custom-fields/{field_id}",
    summary="Get a custom field definition",
    openapi_extra=permission_extra(READ_PERMISSION),
)
async def get_custom_field_route(request: Request, category_id: UUID, field_id: UUID) -> dict[str, Any]:
    del category_id  # the field is addressed by its own id; the category segment stays RESTful
    member = _resolve_member(request)
    pool = request.app.state.pool
    field = await service.get_custom_field_definition(
        pool, organization_id=UUID(member.organization_id), caller=member, field_id=field_id
    )
    return success_response(data=field.model_dump(mode="json"), request_id=_request_id(request))


@categories_router.patch(
    "/{category_id}/custom-fields/{field_id}",
    summary="Update a custom field definition",
    openapi_extra=permission_extra(WRITE_PERMISSION),
)
async def update_custom_field_route(
    request: Request, category_id: UUID, field_id: UUID, body: CustomFieldDefinitionUpdate
) -> dict[str, Any]:
    del category_id
    member = _resolve_member(request)
    pool = request.app.state.pool
    field = await service.update_custom_field_definition(
        pool,
        organization_id=UUID(member.organization_id),
        caller=member,
        field_id=field_id,
        data=body,
        request_id=_request_id(request),
    )
    return success_response(data=field.model_dump(mode="json"), request_id=_request_id(request))


@categories_router.post(
    "/{category_id}/custom-fields/{field_id}/archive",
    summary="Archive a custom field definition",
    openapi_extra=permission_extra(WRITE_PERMISSION),
)
async def archive_custom_field_route(
    request: Request, category_id: UUID, field_id: UUID, body: CustomFieldDefinitionArchive
) -> dict[str, Any]:
    del category_id
    member = _resolve_member(request)
    pool = request.app.state.pool
    field = await service.archive_custom_field_definition(
        pool,
        organization_id=UUID(member.organization_id),
        caller=member,
        field_id=field_id,
        data=body,
        request_id=_request_id(request),
    )
    return success_response(data=field.model_dump(mode="json"), request_id=_request_id(request))


# ==============================================================================
# Manufacturers and suppliers
# ==============================================================================

manufacturers_router = APIRouter(prefix="/manufacturers", tags=["manufacturers"])
suppliers_router = APIRouter(prefix="/suppliers", tags=["suppliers"])


@manufacturers_router.get("", summary="List manufacturers", openapi_extra=permission_extra(READ_PERMISSION))
async def list_manufacturers_route(
    request: Request, status: str | None = None, after: str | None = None, limit: int = 50
) -> dict[str, Any]:
    member = _resolve_member(request)
    pool = request.app.state.pool
    result = await service.list_manufacturers(
        pool,
        organization_id=UUID(member.organization_id),
        caller=member,
        status=status,
        after=after,
        limit=limit,
    )
    return _page(request, result)


@manufacturers_router.post(
    "", status_code=201, summary="Create a manufacturer", openapi_extra=permission_extra(WRITE_PERMISSION)
)
async def create_manufacturer_route(request: Request, body: ManufacturerCreate) -> dict[str, Any]:
    member = _resolve_member(request)
    pool = request.app.state.pool
    record = await service.create_manufacturer(
        pool,
        organization_id=UUID(member.organization_id),
        caller=member,
        data=body,
        request_id=_request_id(request),
    )
    return success_response(
        data=record.model_dump(mode="json"), request_id=_request_id(request), status_code=201
    )


@manufacturers_router.get(
    "/{manufacturer_id}", summary="Get a manufacturer", openapi_extra=permission_extra(READ_PERMISSION)
)
async def get_manufacturer_route(request: Request, manufacturer_id: UUID) -> dict[str, Any]:
    member = _resolve_member(request)
    pool = request.app.state.pool
    record = await service.get_manufacturer(
        pool, organization_id=UUID(member.organization_id), caller=member, manufacturer_id=manufacturer_id
    )
    return success_response(data=record.model_dump(mode="json"), request_id=_request_id(request))


@manufacturers_router.patch(
    "/{manufacturer_id}", summary="Update a manufacturer", openapi_extra=permission_extra(WRITE_PERMISSION)
)
async def update_manufacturer_route(
    request: Request, manufacturer_id: UUID, body: ManufacturerUpdate
) -> dict[str, Any]:
    member = _resolve_member(request)
    pool = request.app.state.pool
    record = await service.update_manufacturer(
        pool,
        organization_id=UUID(member.organization_id),
        caller=member,
        manufacturer_id=manufacturer_id,
        data=body,
        request_id=_request_id(request),
    )
    return success_response(data=record.model_dump(mode="json"), request_id=_request_id(request))


@manufacturers_router.post(
    "/{manufacturer_id}/archive",
    summary="Archive a manufacturer",
    openapi_extra=permission_extra(WRITE_PERMISSION),
)
async def archive_manufacturer_route(
    request: Request, manufacturer_id: UUID, body: ManufacturerArchive
) -> dict[str, Any]:
    member = _resolve_member(request)
    pool = request.app.state.pool
    record = await service.archive_manufacturer(
        pool,
        organization_id=UUID(member.organization_id),
        caller=member,
        manufacturer_id=manufacturer_id,
        data=body,
        request_id=_request_id(request),
    )
    return success_response(data=record.model_dump(mode="json"), request_id=_request_id(request))


@suppliers_router.get("", summary="List suppliers", openapi_extra=permission_extra(READ_PERMISSION))
async def list_suppliers_route(
    request: Request, status: str | None = None, after: str | None = None, limit: int = 50
) -> dict[str, Any]:
    member = _resolve_member(request)
    pool = request.app.state.pool
    result = await service.list_suppliers(
        pool,
        organization_id=UUID(member.organization_id),
        caller=member,
        status=status,
        after=after,
        limit=limit,
    )
    return _page(request, result)


@suppliers_router.post(
    "", status_code=201, summary="Create a supplier", openapi_extra=permission_extra(WRITE_PERMISSION)
)
async def create_supplier_route(request: Request, body: SupplierCreate) -> dict[str, Any]:
    member = _resolve_member(request)
    pool = request.app.state.pool
    record = await service.create_supplier(
        pool,
        organization_id=UUID(member.organization_id),
        caller=member,
        data=body,
        request_id=_request_id(request),
    )
    return success_response(
        data=record.model_dump(mode="json"), request_id=_request_id(request), status_code=201
    )


@suppliers_router.get(
    "/{supplier_id}", summary="Get a supplier", openapi_extra=permission_extra(READ_PERMISSION)
)
async def get_supplier_route(request: Request, supplier_id: UUID) -> dict[str, Any]:
    member = _resolve_member(request)
    pool = request.app.state.pool
    record = await service.get_supplier(
        pool, organization_id=UUID(member.organization_id), caller=member, supplier_id=supplier_id
    )
    return success_response(data=record.model_dump(mode="json"), request_id=_request_id(request))


@suppliers_router.patch(
    "/{supplier_id}", summary="Update a supplier", openapi_extra=permission_extra(WRITE_PERMISSION)
)
async def update_supplier_route(request: Request, supplier_id: UUID, body: SupplierUpdate) -> dict[str, Any]:
    member = _resolve_member(request)
    pool = request.app.state.pool
    record = await service.update_supplier(
        pool,
        organization_id=UUID(member.organization_id),
        caller=member,
        supplier_id=supplier_id,
        data=body,
        request_id=_request_id(request),
    )
    return success_response(data=record.model_dump(mode="json"), request_id=_request_id(request))


@suppliers_router.post(
    "/{supplier_id}/archive", summary="Archive a supplier", openapi_extra=permission_extra(WRITE_PERMISSION)
)
async def archive_supplier_route(
    request: Request, supplier_id: UUID, body: SupplierArchive
) -> dict[str, Any]:
    member = _resolve_member(request)
    pool = request.app.state.pool
    record = await service.archive_supplier(
        pool,
        organization_id=UUID(member.organization_id),
        caller=member,
        supplier_id=supplier_id,
        data=body,
        request_id=_request_id(request),
    )
    return success_response(data=record.model_dump(mode="json"), request_id=_request_id(request))


router.include_router(categories_router)
router.include_router(manufacturers_router)
router.include_router(suppliers_router)
