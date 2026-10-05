# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Catalog reference data service: categories, custom field definitions, manufacturers, suppliers
(master M2.1-T1/T2 data, §B8.1, §B7.1, §B5.9, P8-06).

Writes need `asset.update` held at **organization** scope (reference data is organization-wide, so
a narrower org-unit/team/self grant of the same permission does not count, §B7.1); reads need
`asset.read` at any scope, including the baseline `self` scope, because a member must see the
category and fields of the assets they hold (open point in the plan: the master names no separate
permission for managing this reference data).

Every write is one transaction with its audit event and outbox row (§C4.3); archive is status-only
(no hard delete, §C1.4); list methods always take a `ScopeFilter`, passed as
`ScopeFilter.all_organization()` once the permission check above has already run, since this data
has no per-row scope attribute of its own to filter on (Must-not rule in the plan).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from app.core.db import Pool, tenant_transaction
from app.core.ids import uuid7
from app.core.permissions import ScopeFilter
from app.core.problems import PermissionDeniedError, ValidationFailedError
from app.core.scope import MemberContext, default_scope_resolver
from app.modules.assets.catalog import repository as repo
from app.modules.assets.catalog.errors import (
    CategoryArchiveBlockedError,
    CategoryConflictError,
    CategoryInvalidMoveError,
    CategoryNotFoundError,
    CategoryVersionConflictError,
    CustomFieldDefinitionConflictError,
    CustomFieldDefinitionNotFoundError,
)
from app.modules.assets.catalog.schemas import (
    CategoryArchive,
    CategoryCreate,
    CategoryMove,
    CategoryRead,
    CategoryUpdate,
    CustomFieldDefinitionCreate,
    CustomFieldDefinitionRead,
)
from app.modules.assets.config import CustomField as TemplateCustomField
from app.modules.assets.custom_fields import MAX_REGEX_PATTERN_LENGTH, compile_field_regex
from app.modules.assets.events import (
    ASSET_CATEGORY_ARCHIVED,
    ASSET_CATEGORY_CREATED,
    ASSET_CATEGORY_MOVED,
    ASSET_CATEGORY_UPDATED,
    CUSTOM_FIELD_DEFINITION_CREATED,
)
from app.modules.audit.service import record_audit_event

__all__ = [
    "CursorPage",
    "archive_category",
    "create_category",
    "create_custom_field_definition",
    "get_category",
    "get_custom_field_definition",
    "list_categories",
    "list_custom_field_definitions",
    "move_category",
    "update_category",
]

READ_PERMISSION = "asset.read"
WRITE_PERMISSION = "asset.update"

_category_repo = repo.CategoryRepository()
_field_repo = repo.CustomFieldDefinitionRepository()
_manufacturer_repo = repo.ManufacturerRepository()
_supplier_repo = repo.SupplierRepository()

DEFAULT_PAGE_SIZE = 50


@dataclass(frozen=True)
class CursorPage:
    """One page of a cursor-paginated list (§B4.5, §C1.5)."""

    items: list[dict[str, Any]]
    next_cursor: str | None


def _require_write(caller: MemberContext) -> None:
    """Writes need `asset.update` at organization scope (this data is organization-wide)."""
    scope_filter = default_scope_resolver.resolve_scope_filter(caller, WRITE_PERMISSION)
    if not scope_filter.organization:
        raise PermissionDeniedError(f"Permission {WRITE_PERMISSION!r} is required at organization scope.")


def _require_read(caller: MemberContext) -> None:
    """Reads need `asset.read` at any scope, including `self` (a member sees their own assets' data)."""
    default_scope_resolver.require(caller, READ_PERMISSION, None)


def _list_scope_filter() -> ScopeFilter:
    """Organization-wide: the permission check above already gated the call (Must-not rule)."""
    return ScopeFilter.all_organization()


def _actor_id(caller: MemberContext) -> UUID | None:
    try:
        return UUID(caller.member_id)
    except (ValueError, AttributeError):
        return None


async def _outbox(
    conn: Any,
    *,
    organization_id: UUID,
    event_type: str,
    aggregate_type: str,
    aggregate_id: UUID,
    payload: dict[str, Any],
) -> None:
    await conn.execute(
        "INSERT INTO public.outbox "
        "(id, organization_id, event_type, aggregate_type, aggregate_id, payload) "
        "VALUES ($1, $2, $3, $4, $5, $6::jsonb)",
        uuid7(),
        organization_id,
        event_type,
        aggregate_type,
        aggregate_id,
        json.dumps(payload),
    )


# ==============================================================================
# Asset categories
# ==============================================================================


async def list_categories(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    status: str | None = None,
    parent_id: UUID | None = None,
    after: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
) -> CursorPage:
    _require_read(caller)
    scope_filter = _list_scope_filter()
    cursor = repo.decode_cursor(after) if after else None
    async with tenant_transaction(pool, organization_id) as conn:
        rows = await _category_repo.list_page(
            conn,
            organization_id=organization_id,
            scope_filter=scope_filter,
            status=status,
            parent_id=parent_id,
            after=cursor,
            limit=limit,
        )
    items = [CategoryRead.model_validate(dict(row)).model_dump(mode="json") for row in rows]
    next_cursor = repo.encode_cursor(rows[-1]["code"], rows[-1]["id"]) if len(rows) == limit else None
    return CursorPage(items=items, next_cursor=next_cursor)


async def get_category(
    pool: Pool, *, organization_id: UUID, caller: MemberContext, category_id: UUID
) -> CategoryRead:
    _require_read(caller)
    async with tenant_transaction(pool, organization_id) as conn:
        row = await _category_repo.get_by_id(conn, organization_id=organization_id, category_id=category_id)
    if row is None:
        raise CategoryNotFoundError()
    return CategoryRead.model_validate(dict(row))


async def create_category(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    data: CategoryCreate,
    request_id: str | None = None,
) -> CategoryRead:
    _require_write(caller)
    async with tenant_transaction(pool, organization_id) as conn:
        parent_path: str | None = None
        if data.parent_id is not None:
            parent = await _category_repo.get_by_id(
                conn, organization_id=organization_id, category_id=data.parent_id, for_update=True
            )
            if parent is None:
                raise CategoryNotFoundError("Parent category not found")
            parent_path = parent["path"]

        existing = await _category_repo.get_by_code(conn, organization_id=organization_id, code=data.code)
        if existing is not None:
            raise CategoryConflictError(f"An asset category with code {data.code!r} already exists")

        label = repo.to_ltree_label(data.code)
        path = f"{parent_path}.{label}" if parent_path else label
        category_id = uuid7()

        row = await _category_repo.create(
            conn,
            category_id=category_id,
            organization_id=organization_id,
            parent_id=data.parent_id,
            path=path,
            code=data.code,
            name=data.name,
            tag_prefix=data.tag_prefix,
            default_criticality=data.default_criticality,
            responsible_team_id=data.responsible_team_id,
        )

        await record_audit_event(
            conn,
            organization_id=organization_id,
            actor_member_id=_actor_id(caller),
            action="asset_category.create",
            entity_type="asset_category",
            entity_id=category_id,
            request_id=request_id,
            after_state=dict(row),
        )
        await _outbox(
            conn,
            organization_id=organization_id,
            event_type=ASSET_CATEGORY_CREATED,
            aggregate_type="asset_category",
            aggregate_id=category_id,
            payload={
                "id": str(category_id),
                "code": data.code,
                "path": path,
                "parent_id": str(data.parent_id) if data.parent_id else None,
            },
        )
    return CategoryRead.model_validate(dict(row))


async def update_category(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    category_id: UUID,
    data: CategoryUpdate,
    request_id: str | None = None,
) -> CategoryRead:
    _require_write(caller)
    async with tenant_transaction(pool, organization_id) as conn:
        current = await _category_repo.get_by_id(
            conn, organization_id=organization_id, category_id=category_id, for_update=True
        )
        if current is None:
            raise CategoryNotFoundError()

        row = await _category_repo.update(
            conn,
            organization_id=organization_id,
            category_id=category_id,
            version=data.version,
            name=data.name,
            tag_prefix=data.tag_prefix,
            clear_tag_prefix=data.clear_tag_prefix,
            default_criticality=data.default_criticality,
            clear_default_criticality=data.clear_default_criticality,
            responsible_team_id=data.responsible_team_id,
            clear_responsible_team=data.clear_responsible_team,
        )
        if row is None:
            raise CategoryVersionConflictError()

        await record_audit_event(
            conn,
            organization_id=organization_id,
            actor_member_id=_actor_id(caller),
            action="asset_category.update",
            entity_type="asset_category",
            entity_id=category_id,
            request_id=request_id,
            before_state=dict(current),
            after_state=dict(row),
        )
        await _outbox(
            conn,
            organization_id=organization_id,
            event_type=ASSET_CATEGORY_UPDATED,
            aggregate_type="asset_category",
            aggregate_id=category_id,
            payload={"id": str(category_id), "name": row["name"]},
        )
    return CategoryRead.model_validate(dict(row))


async def move_category(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    category_id: UUID,
    data: CategoryMove,
    request_id: str | None = None,
) -> CategoryRead:
    _require_write(caller)
    async with tenant_transaction(pool, organization_id) as conn:
        current = await _category_repo.get_by_id(
            conn, organization_id=organization_id, category_id=category_id, for_update=True
        )
        if current is None:
            raise CategoryNotFoundError()
        if data.new_parent_id == category_id:
            raise CategoryInvalidMoveError("Cannot move a category into itself")

        new_parent = await _category_repo.get_by_id(
            conn, organization_id=organization_id, category_id=data.new_parent_id, for_update=True
        )
        if new_parent is None:
            raise CategoryNotFoundError("Destination parent category not found")

        old_path, new_parent_path = current["path"], new_parent["path"]
        if new_parent_path == old_path or new_parent_path.startswith(f"{old_path}."):
            raise CategoryInvalidMoveError("Cannot move a category into its own descendant")

        label = repo.to_ltree_label(current["code"])
        new_path = f"{new_parent_path}.{label}"

        row = await _category_repo.move(
            conn,
            organization_id=organization_id,
            category_id=category_id,
            version=data.version,
            new_parent_id=data.new_parent_id,
            old_path=old_path,
            new_path=new_path,
        )
        if row is None:
            raise CategoryVersionConflictError()

        await record_audit_event(
            conn,
            organization_id=organization_id,
            actor_member_id=_actor_id(caller),
            action="asset_category.moved",
            entity_type="asset_category",
            entity_id=category_id,
            request_id=request_id,
            before_state={"parent_id": str(current["parent_id"]), "path": old_path},
            after_state={"parent_id": str(data.new_parent_id), "path": new_path},
        )
        await _outbox(
            conn,
            organization_id=organization_id,
            event_type=ASSET_CATEGORY_MOVED,
            aggregate_type="asset_category",
            aggregate_id=category_id,
            payload={
                "id": str(category_id),
                "old_path": old_path,
                "new_path": new_path,
                "new_parent_id": str(data.new_parent_id),
            },
        )
    return CategoryRead.model_validate(dict(row))


async def archive_category(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    category_id: UUID,
    data: CategoryArchive,
    request_id: str | None = None,
) -> CategoryRead:
    _require_write(caller)
    async with tenant_transaction(pool, organization_id) as conn:
        current = await _category_repo.get_by_id(
            conn, organization_id=organization_id, category_id=category_id, for_update=True
        )
        if current is None:
            raise CategoryNotFoundError()

        active_children = await _category_repo.count_active_children(
            conn, organization_id=organization_id, category_id=category_id
        )
        if active_children > 0:
            raise CategoryArchiveBlockedError(
                f"Cannot archive category with {active_children} active child categories "
                f"(blocker: active_children)"
            )
        assets_using = await _category_repo.count_assets_using(
            conn, organization_id=organization_id, category_id=category_id
        )
        if assets_using > 0:
            raise CategoryArchiveBlockedError(
                f"Cannot archive category with {assets_using} assets still assigned to it (blocker: assets)"
            )

        row = await _category_repo.archive(
            conn, organization_id=organization_id, category_id=category_id, version=data.version
        )
        if row is None:
            raise CategoryVersionConflictError()

        await record_audit_event(
            conn,
            organization_id=organization_id,
            actor_member_id=_actor_id(caller),
            action="asset_category.archive",
            entity_type="asset_category",
            entity_id=category_id,
            request_id=request_id,
            before_state=dict(current),
            after_state=dict(row),
        )
        await _outbox(
            conn,
            organization_id=organization_id,
            event_type=ASSET_CATEGORY_ARCHIVED,
            aggregate_type="asset_category",
            aggregate_id=category_id,
            payload={"id": str(category_id), "code": row["code"]},
        )
    return CategoryRead.model_validate(dict(row))


# ==============================================================================
# Custom field definitions
# ==============================================================================


def _build_rules(
    min_: float | None, max_: float | None, regex: str | None, options: list[str]
) -> dict[str, object]:
    rules: dict[str, object] = {}
    if min_ is not None:
        rules["min"] = min_
    if max_ is not None:
        rules["max"] = max_
    if regex is not None:
        rules["regex"] = regex
    if options:
        rules["options"] = options
    return rules


def _validate_definition_shape(
    *,
    key: str,
    label: str,
    field_type: str,
    is_required: bool,
    min_: float | None,
    max_: float | None,
    regex: str | None,
    options: list[str],
    is_unique: bool,
    is_encrypted: bool,
) -> None:
    """Definition-time checks (P8-04 rules): reuses the domain-template `CustomField` model, which
    already enforces min <= max, non-empty/unique options for select types, a compiling regex and
    "an encrypted field cannot be unique". Adds the regex-length cap `custom_fields.py` relies on."""
    if regex is not None and len(regex) > MAX_REGEX_PATTERN_LENGTH:
        raise ValidationFailedError(f"regex must be at most {MAX_REGEX_PATTERN_LENGTH} characters")
    try:
        TemplateCustomField(
            key=key,
            label=label,
            type=field_type,
            required=is_required,
            min=min_,
            max=max_,
            regex=regex,
            options=options,
            is_unique=is_unique,
            is_encrypted=is_encrypted,
        )
    except ValidationError as exc:
        first = exc.errors()[0]
        raise ValidationFailedError(first["msg"].removeprefix("Value error, ")) from exc
    if regex is not None:
        compile_field_regex(regex)  # pre-compiles and caches; raises ValueError if ever over-length


async def list_custom_field_definitions(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    category_id: UUID,
    status: str | None = None,
    after: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
) -> CursorPage:
    _require_read(caller)
    scope_filter = _list_scope_filter()
    cursor = repo.decode_cursor(after) if after else None
    async with tenant_transaction(pool, organization_id) as conn:
        category = await _category_repo.get_by_id(
            conn, organization_id=organization_id, category_id=category_id
        )
        if category is None:
            raise CategoryNotFoundError()
        rows = await _field_repo.list_by_category(
            conn,
            organization_id=organization_id,
            scope_filter=scope_filter,
            category_id=category_id,
            status=status,
            after=cursor,
            limit=limit,
        )
    items = [
        CustomFieldDefinitionRead.model_validate(_field_dict(row)).model_dump(mode="json") for row in rows
    ]
    next_cursor = repo.encode_cursor(rows[-1]["key"], rows[-1]["id"]) if len(rows) == limit else None
    return CursorPage(items=items, next_cursor=next_cursor)


def _field_dict(row: Any) -> dict[str, Any]:
    out = dict(row)
    if isinstance(out.get("rules"), str):
        out["rules"] = json.loads(out["rules"])
    return out


async def get_custom_field_definition(
    pool: Pool, *, organization_id: UUID, caller: MemberContext, field_id: UUID
) -> CustomFieldDefinitionRead:
    _require_read(caller)
    async with tenant_transaction(pool, organization_id) as conn:
        row = await _field_repo.get_by_id(conn, organization_id=organization_id, field_id=field_id)
    if row is None:
        raise CustomFieldDefinitionNotFoundError()
    return CustomFieldDefinitionRead.model_validate(_field_dict(row))


async def create_custom_field_definition(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    category_id: UUID,
    data: CustomFieldDefinitionCreate,
    request_id: str | None = None,
) -> CustomFieldDefinitionRead:
    _require_write(caller)
    _validate_definition_shape(
        key=data.key,
        label=data.label,
        field_type=data.field_type,
        is_required=data.is_required,
        min_=data.min,
        max_=data.max,
        regex=data.regex,
        options=data.options,
        is_unique=data.is_unique,
        is_encrypted=data.is_encrypted,
    )
    async with tenant_transaction(pool, organization_id) as conn:
        category = await _category_repo.get_by_id(
            conn, organization_id=organization_id, category_id=category_id, for_update=True
        )
        if category is None:
            raise CategoryNotFoundError()

        existing = await _field_repo.get_by_key(
            conn, organization_id=organization_id, category_id=category_id, key=data.key
        )
        if existing is not None:
            raise CustomFieldDefinitionConflictError(
                f"A custom field with key {data.key!r} already exists on this category"
            )

        field_id = uuid7()
        rules = _build_rules(data.min, data.max, data.regex, data.options)
        row = await _field_repo.create(
            conn,
            field_id=field_id,
            organization_id=organization_id,
            category_id=category_id,
            key=data.key,
            label=data.label,
            field_type=data.field_type,
            is_required=data.is_required,
            rules=rules,
            is_unique=data.is_unique,
            is_encrypted=data.is_encrypted,
            position=data.position,
        )

        await record_audit_event(
            conn,
            organization_id=organization_id,
            actor_member_id=_actor_id(caller),
            action="custom_field_definition.create",
            entity_type="custom_field_definition",
            entity_id=field_id,
            request_id=request_id,
            after_state=_field_dict(row),
        )
        await _outbox(
            conn,
            organization_id=organization_id,
            event_type=CUSTOM_FIELD_DEFINITION_CREATED,
            aggregate_type="custom_field_definition",
            aggregate_id=field_id,
            payload={
                "id": str(field_id),
                "category_id": str(category_id),
                "key": data.key,
                "field_type": data.field_type,
            },
        )
    return CustomFieldDefinitionRead.model_validate(_field_dict(row))
