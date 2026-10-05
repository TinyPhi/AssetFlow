# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Saved asset list views: schemas, repository, service and routes (§B8.1, M2.1-T5, P8-07 step 7).

A saved view belongs to one member and stores the list query (filters), the sort and the visible
columns, nothing else. Applying a view means the client sends its query to `GET /api/v1/assets`, so
the normal scoped list runs and a view can never widen access. Every change is one transaction with
its audit event and outbox row. Another member's view answers 404, like any record outside scope.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.db import Pool, tenant_transaction
from app.core.envelope import success_response
from app.core.ids import uuid7
from app.core.openapi_meta import permission_extra
from app.core.problems import FieldError, ValidationFailedError
from app.core.scope import MemberContext, default_scope_resolver
from app.modules.assets.errors import (
    AssetSavedViewNameConflictError,
    AssetSavedViewNotFoundError,
    AssetSavedViewVersionConflictError,
)
from app.modules.assets.events import (
    ASSET_SAVED_VIEW_CREATED,
    ASSET_SAVED_VIEW_DELETED,
    ASSET_SAVED_VIEW_UPDATED,
)
from app.modules.assets.permissions import READ_PERMISSION
from app.modules.assets.repository import SORT_COLUMNS, DbConn
from app.modules.assets.router import _request_id, _resolve_member
from app.modules.assets.schemas import AssetListItem
from app.modules.audit.service import record_audit_event
from app.modules.organization.modules import require_module

__all__ = [
    "SavedViewCreate",
    "SavedViewRead",
    "SavedViewRepository",
    "SavedViewUpdate",
    "router",
]

#: Filter names a view may store: exactly the list endpoint's query parameters (plus `cf.<key>`).
QUERY_KEYS = frozenset(
    {
        "q",
        "status",
        "status_category",
        "category_id",
        "include_subcategories",
        "owner_org_unit_id",
        "include_sub_units",
        "location_id",
        "include_sub_locations",
        "holder_type",
        "holder_member_id",
        "holder_team_id",
        "criticality",
        "manufacturer_id",
        "supplier_id",
        "warranty_end_before",
        "warranty_end_after",
        "purchase_date_before",
        "purchase_date_after",
        "updated_since",
    }
)
_CF_KEY = re.compile(r"^cf\.[a-z][a-z0-9_]*(\.(gte|lte))?$")
_COLUMNS = frozenset(AssetListItem.model_fields)
_MAX_VIEWS = 200
_MAX_QUERY_BYTES = 8192

_SELECT = (
    "SELECT id, name, query, sort, columns, version, created_at, updated_at FROM public.asset_saved_views"
)


def _check_query(query: dict[str, Any]) -> dict[str, Any]:
    errors: list[FieldError] = []
    for key, value in query.items():
        if key not in QUERY_KEYS and not _CF_KEY.match(key):
            errors.append(FieldError(field=f"query.{key}", message="not a list filter"))
        scalars = value if isinstance(value, list) else [value]
        if not all(isinstance(v, str | int | float | bool) for v in scalars):
            errors.append(FieldError(field=f"query.{key}", message="must be a scalar or a list of scalars"))
    if len(json.dumps(query)) > _MAX_QUERY_BYTES:
        errors.append(FieldError(field="query", message="too large"))
    if errors:
        raise ValidationFailedError(errors=errors)
    return query


def _check_sort(sort: str) -> str:
    if sort.removeprefix("-") not in SORT_COLUMNS:
        raise ValidationFailedError(errors=[FieldError(field="sort", message=f'unknown sort key "{sort}"')])
    return sort


def _check_columns(columns: list[str]) -> list[str]:
    unknown = sorted(set(columns) - _COLUMNS)
    if unknown:
        raise ValidationFailedError(
            errors=[FieldError(field="columns", message=f"unknown column(s): {', '.join(unknown)}")]
        )
    return columns


class SavedViewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=100)]
    query: dict[str, Any] = Field(default_factory=dict)
    sort: str = "-created_at"
    columns: list[str] = Field(default_factory=list, max_length=len(_COLUMNS))

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()


class SavedViewUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    name: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    query: dict[str, Any] | None = None
    sort: str | None = None
    columns: list[str] | None = Field(default=None, max_length=len(_COLUMNS))

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value.strip() if value is not None else None


class SavedViewRead(BaseModel):
    id: UUID
    name: str
    query: dict[str, Any]
    sort: str
    columns: list[str]
    version: int
    created_at: datetime
    updated_at: datetime


# ==============================================================================
# Repository
# ==============================================================================


class SavedViewRepository:
    """Every method filters on the owning member as well as the organization: a view is private."""

    async def list_own(
        self, conn: DbConn, *, organization_id: UUID, member_id: UUID, limit: int = _MAX_VIEWS
    ) -> list[asyncpg.Record]:
        return await conn.fetch(
            f"{_SELECT} WHERE organization_id = $1 AND member_id = $2 ORDER BY name, id LIMIT $3",
            organization_id,
            member_id,
            limit,
        )

    async def get_own(
        self,
        conn: DbConn,
        *,
        organization_id: UUID,
        member_id: UUID,
        view_id: UUID,
        for_update: bool = False,
    ) -> asyncpg.Record | None:
        lock = " FOR UPDATE" if for_update else ""
        return await conn.fetchrow(
            f"{_SELECT} WHERE organization_id = $1 AND member_id = $2 AND id = $3{lock}",
            organization_id,
            member_id,
            view_id,
        )

    async def insert(
        self,
        conn: DbConn,
        *,
        view_id: UUID,
        organization_id: UUID,
        member_id: UUID,
        data: SavedViewCreate,
    ) -> asyncpg.Record:
        row = await conn.fetchrow(
            "INSERT INTO public.asset_saved_views "
            "(id, organization_id, member_id, name, query, sort, columns) "
            "VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7::text[]) "
            "RETURNING id, name, query, sort, columns, version, created_at, updated_at",
            view_id,
            organization_id,
            member_id,
            data.name,
            json.dumps(data.query),
            data.sort,
            data.columns,
        )
        assert row is not None  # noqa: S101 - INSERT ... RETURNING always returns one row
        return row

    async def update(
        self,
        conn: DbConn,
        *,
        organization_id: UUID,
        member_id: UUID,
        view_id: UUID,
        version: int,
        name: str,
        query: dict[str, Any],
        sort: str,
        columns: list[str],
    ) -> asyncpg.Record | None:
        return await conn.fetchrow(
            "UPDATE public.asset_saved_views SET name = $5, query = $6::jsonb, sort = $7, "
            "columns = $8::text[], version = version + 1, updated_at = now() "
            "WHERE organization_id = $1 AND member_id = $2 AND id = $3 AND version = $4 "
            "RETURNING id, name, query, sort, columns, version, created_at, updated_at",
            organization_id,
            member_id,
            view_id,
            version,
            name,
            json.dumps(query),
            sort,
            columns,
        )

    async def delete(self, conn: DbConn, *, organization_id: UUID, member_id: UUID, view_id: UUID) -> bool:
        result = await conn.execute(
            "DELETE FROM public.asset_saved_views WHERE organization_id = $1 AND member_id = $2 AND id = $3",
            organization_id,
            member_id,
            view_id,
        )
        return result == "DELETE 1"


_repo = SavedViewRepository()


# ==============================================================================
# Service
# ==============================================================================


def _actor(caller: MemberContext) -> UUID:
    return UUID(caller.member_id)


def _read(row: asyncpg.Record) -> SavedViewRead:
    data = dict(row)
    if isinstance(data["query"], str):
        data["query"] = json.loads(data["query"])
    data["columns"] = list(data["columns"])
    return SavedViewRead.model_validate(data)


async def _outbox(
    conn: DbConn, organization_id: UUID, event_type: str, view_id: UUID, payload: dict[str, Any]
) -> None:
    await conn.execute(
        "INSERT INTO public.outbox "
        "(id, organization_id, event_type, aggregate_type, aggregate_id, payload) "
        "VALUES ($1, $2, $3, 'asset_saved_view', $4, $5::jsonb)",
        uuid7(),
        organization_id,
        event_type,
        view_id,
        json.dumps(payload),
    )


async def list_views(pool: Pool, *, caller: MemberContext) -> list[SavedViewRead]:
    default_scope_resolver.require(caller, READ_PERMISSION, None)
    organization_id = UUID(caller.organization_id)
    async with tenant_transaction(pool, organization_id) as conn:
        rows = await _repo.list_own(conn, organization_id=organization_id, member_id=_actor(caller))
    return [_read(r) for r in rows]


async def create_view(
    pool: Pool, *, caller: MemberContext, data: SavedViewCreate, request_id: str | None = None
) -> SavedViewRead:
    default_scope_resolver.require(caller, READ_PERMISSION, None)
    _check_query(data.query)
    _check_sort(data.sort)
    _check_columns(data.columns)
    organization_id = UUID(caller.organization_id)
    view_id = uuid7()
    async with tenant_transaction(pool, organization_id) as conn:
        try:
            row = await _repo.insert(
                conn, view_id=view_id, organization_id=organization_id, member_id=_actor(caller), data=data
            )
        except asyncpg.UniqueViolationError as exc:
            raise AssetSavedViewNameConflictError() from exc
        await record_audit_event(
            conn,
            organization_id=organization_id,
            actor_member_id=_actor(caller),
            action="asset_saved_view.create",
            entity_type="asset_saved_view",
            entity_id=view_id,
            request_id=request_id,
            after_state={"name": data.name, "sort": data.sort, "columns": data.columns},
        )
        await _outbox(conn, organization_id, ASSET_SAVED_VIEW_CREATED, view_id, {"id": str(view_id)})
    return _read(row)


async def update_view(
    pool: Pool,
    *,
    caller: MemberContext,
    view_id: UUID,
    data: SavedViewUpdate,
    request_id: str | None = None,
) -> SavedViewRead:
    default_scope_resolver.require(caller, READ_PERMISSION, None)
    if data.query is not None:
        _check_query(data.query)
    if data.sort is not None:
        _check_sort(data.sort)
    if data.columns is not None:
        _check_columns(data.columns)
    organization_id = UUID(caller.organization_id)
    async with tenant_transaction(pool, organization_id) as conn:
        current = await _repo.get_own(
            conn, organization_id=organization_id, member_id=_actor(caller), view_id=view_id, for_update=True
        )
        if current is None:
            raise AssetSavedViewNotFoundError()
        before = _read(current)
        try:
            row = await _repo.update(
                conn,
                organization_id=organization_id,
                member_id=_actor(caller),
                view_id=view_id,
                version=data.version,
                name=data.name if data.name is not None else before.name,
                query=data.query if data.query is not None else before.query,
                sort=data.sort if data.sort is not None else before.sort,
                columns=data.columns if data.columns is not None else before.columns,
            )
        except asyncpg.UniqueViolationError as exc:
            raise AssetSavedViewNameConflictError() from exc
        if row is None:
            raise AssetSavedViewVersionConflictError()
        after = _read(row)
        await record_audit_event(
            conn,
            organization_id=organization_id,
            actor_member_id=_actor(caller),
            action="asset_saved_view.update",
            entity_type="asset_saved_view",
            entity_id=view_id,
            request_id=request_id,
            before_state={"name": before.name, "sort": before.sort, "columns": before.columns},
            after_state={"name": after.name, "sort": after.sort, "columns": after.columns},
        )
        await _outbox(
            conn,
            organization_id,
            ASSET_SAVED_VIEW_UPDATED,
            view_id,
            {"id": str(view_id), "version": after.version},
        )
    return after


async def delete_view(
    pool: Pool, *, caller: MemberContext, view_id: UUID, request_id: str | None = None
) -> None:
    default_scope_resolver.require(caller, READ_PERMISSION, None)
    organization_id = UUID(caller.organization_id)
    async with tenant_transaction(pool, organization_id) as conn:
        current = await _repo.get_own(
            conn, organization_id=organization_id, member_id=_actor(caller), view_id=view_id, for_update=True
        )
        if current is None:
            raise AssetSavedViewNotFoundError()
        await _repo.delete(conn, organization_id=organization_id, member_id=_actor(caller), view_id=view_id)
        await record_audit_event(
            conn,
            organization_id=organization_id,
            actor_member_id=_actor(caller),
            action="asset_saved_view.delete",
            entity_type="asset_saved_view",
            entity_id=view_id,
            request_id=request_id,
            before_state={"name": current["name"]},
        )
        await _outbox(conn, organization_id, ASSET_SAVED_VIEW_DELETED, view_id, {"id": str(view_id)})


# ==============================================================================
# Routes
# ==============================================================================

router = APIRouter(
    prefix="/asset-saved-views", tags=["assets"], dependencies=[Depends(require_module("assets"))]
)


@router.get("", summary="List my saved asset views", openapi_extra=permission_extra(READ_PERMISSION))
async def list_views_route(request: Request) -> dict[str, Any]:
    views = await list_views(request.app.state.pool, caller=_resolve_member(request))
    return success_response(
        data={"items": [v.model_dump(mode="json") for v in views]}, request_id=_request_id(request)
    )


@router.post(
    "",
    status_code=201,
    summary="Save an asset list view",
    openapi_extra=permission_extra(READ_PERMISSION),
)
async def create_view_route(request: Request, body: SavedViewCreate) -> dict[str, Any]:
    view = await create_view(
        request.app.state.pool,
        caller=_resolve_member(request),
        data=body,
        request_id=_request_id(request),
    )
    return success_response(
        data=view.model_dump(mode="json"), request_id=_request_id(request), status_code=201
    )


@router.patch("/{view_id}", summary="Edit a saved view", openapi_extra=permission_extra(READ_PERMISSION))
async def update_view_route(request: Request, view_id: UUID, body: SavedViewUpdate) -> dict[str, Any]:
    view = await update_view(
        request.app.state.pool,
        caller=_resolve_member(request),
        view_id=view_id,
        data=body,
        request_id=_request_id(request),
    )
    return success_response(data=view.model_dump(mode="json"), request_id=_request_id(request))


@router.delete("/{view_id}", summary="Delete a saved view", openapi_extra=permission_extra(READ_PERMISSION))
async def delete_view_route(request: Request, view_id: UUID) -> dict[str, Any]:
    await delete_view(
        request.app.state.pool,
        caller=_resolve_member(request),
        view_id=view_id,
        request_id=_request_id(request),
    )
    return success_response(data={"id": str(view_id)}, request_id=_request_id(request))
