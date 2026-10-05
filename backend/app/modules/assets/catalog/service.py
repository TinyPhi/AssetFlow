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
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from pydantic import ValidationError

from app.core.config import resolve_config_path
from app.core.db import Pool, tenant_transaction
from app.core.ids import uuid7
from app.core.permissions import ScopeFilter
from app.core.problems import PermissionDeniedError, ScopeDeniedError, ValidationFailedError
from app.core.scope import MemberContext, default_scope_resolver
from app.engines.automation.domain_template import DomainTemplateError, load_domain_template
from app.modules.assets.catalog import repository as repo
from app.modules.assets.catalog.errors import (
    CategoryArchiveBlockedError,
    CategoryConflictError,
    CategoryInvalidMoveError,
    CategoryNotFoundError,
    CategoryVersionConflictError,
    CustomFieldDefinitionConflictError,
    CustomFieldDefinitionNotFoundError,
    CustomFieldDefinitionVersionConflictError,
    CustomFieldTypeChangeBlockedError,
    ManufacturerConflictError,
    ManufacturerNotFoundError,
    ManufacturerVersionConflictError,
    SupplierConflictError,
    SupplierNotFoundError,
    SupplierVersionConflictError,
)
from app.modules.assets.catalog.schemas import (
    CategoryArchive,
    CategoryCreate,
    CategoryMove,
    CategoryRead,
    CategoryUpdate,
    CustomFieldDefinitionArchive,
    CustomFieldDefinitionCreate,
    CustomFieldDefinitionRead,
    CustomFieldDefinitionUpdate,
    ManufacturerArchive,
    ManufacturerCreate,
    ManufacturerRead,
    ManufacturerUpdate,
    SupplierArchive,
    SupplierCreate,
    SupplierRead,
    SupplierUpdate,
)
from app.modules.assets.config import CustomField as TemplateCustomField
from app.modules.assets.config import parse_assets_section
from app.modules.assets.custom_fields import MAX_REGEX_PATTERN_LENGTH, compile_field_regex
from app.modules.assets.events import (
    ASSET_CATEGORY_ARCHIVED,
    ASSET_CATEGORY_CREATED,
    ASSET_CATEGORY_MOVED,
    ASSET_CATEGORY_SEEDED,
    ASSET_CATEGORY_UPDATED,
    CUSTOM_FIELD_DEFINITION_ARCHIVED,
    CUSTOM_FIELD_DEFINITION_CREATED,
    CUSTOM_FIELD_DEFINITION_UPDATED,
    MANUFACTURER_ARCHIVED,
    MANUFACTURER_CREATED,
    MANUFACTURER_UPDATED,
    SUPPLIER_ARCHIVED,
    SUPPLIER_CREATED,
    SUPPLIER_UPDATED,
)
from app.modules.audit.service import record_audit_event

__all__ = [
    "CursorPage",
    "archive_category",
    "archive_custom_field_definition",
    "archive_manufacturer",
    "archive_supplier",
    "create_category",
    "create_custom_field_definition",
    "create_manufacturer",
    "create_supplier",
    "get_category",
    "get_custom_field_definition",
    "get_manufacturer",
    "get_supplier",
    "list_categories",
    "list_custom_field_definitions",
    "list_manufacturers",
    "list_suppliers",
    "move_category",
    "seed_assets_catalog",
    "update_category",
    "update_custom_field_definition",
    "update_manufacturer",
    "update_supplier",
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
    if scope_filter.organization:
        return
    if not default_scope_resolver.has_permission(caller, WRITE_PERMISSION):
        raise PermissionDeniedError(f"Permission {WRITE_PERMISSION!r} denied.")
    raise ScopeDeniedError(f"Permission {WRITE_PERMISSION!r} is required at organization scope.")


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


async def update_custom_field_definition(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    field_id: UUID,
    data: CustomFieldDefinitionUpdate,
    request_id: str | None = None,
) -> CustomFieldDefinitionRead:
    _require_write(caller)
    async with tenant_transaction(pool, organization_id) as conn:
        current = await _field_repo.get_by_id(
            conn, organization_id=organization_id, field_id=field_id, for_update=True
        )
        if current is None:
            raise CustomFieldDefinitionNotFoundError()

        current_rules = (
            json.loads(current["rules"]) if isinstance(current["rules"], str) else dict(current["rules"])
        )
        new_min = current_rules.get("min") if data.min is None and not data.clear_min else data.min
        new_max = current_rules.get("max") if data.max is None and not data.clear_max else data.max
        new_regex = current_rules.get("regex") if data.regex is None and not data.clear_regex else data.regex
        new_options = data.options if data.options is not None else (current_rules.get("options") or [])
        new_field_type = data.field_type or current["field_type"]
        new_is_unique = data.is_unique if data.is_unique is not None else current["is_unique"]
        new_label = data.label or current["label"]

        type_or_rules_changed = new_field_type != current["field_type"]
        if type_or_rules_changed:
            usage = await _field_repo.count_assets_with_value(
                conn, organization_id=organization_id, key=current["key"]
            )
            if usage > 0:
                raise CustomFieldTypeChangeBlockedError()

        _validate_definition_shape(
            key=current["key"],
            label=new_label,
            field_type=new_field_type,
            is_required=data.is_required if data.is_required is not None else current["is_required"],
            min_=new_min,
            max_=new_max,
            regex=new_regex,
            options=new_options,
            is_unique=new_is_unique,
            is_encrypted=current["is_encrypted"],  # immutable
        )

        row = await _field_repo.update(
            conn,
            organization_id=organization_id,
            field_id=field_id,
            version=data.version,
            label=data.label,
            field_type=data.field_type,
            is_required=data.is_required,
            rules=_build_rules(new_min, new_max, new_regex, new_options),
            is_unique=data.is_unique,
            position=data.position,
        )
        if row is None:
            raise CustomFieldDefinitionVersionConflictError()

        await record_audit_event(
            conn,
            organization_id=organization_id,
            actor_member_id=_actor_id(caller),
            action="custom_field_definition.update",
            entity_type="custom_field_definition",
            entity_id=field_id,
            request_id=request_id,
            before_state=_field_dict(current),
            after_state=_field_dict(row),
        )
        await _outbox(
            conn,
            organization_id=organization_id,
            event_type=CUSTOM_FIELD_DEFINITION_UPDATED,
            aggregate_type="custom_field_definition",
            aggregate_id=field_id,
            payload={"id": str(field_id), "category_id": str(row["category_id"]), "key": row["key"]},
        )
    return CustomFieldDefinitionRead.model_validate(_field_dict(row))


async def archive_custom_field_definition(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    field_id: UUID,
    data: CustomFieldDefinitionArchive,
    request_id: str | None = None,
) -> CustomFieldDefinitionRead:
    """Archived fields stay readable on old assets but are not required or accepted on new writes
    (enforced by P8-04's `validate_custom_fields`, which is given only active definitions)."""
    _require_write(caller)
    async with tenant_transaction(pool, organization_id) as conn:
        current = await _field_repo.get_by_id(
            conn, organization_id=organization_id, field_id=field_id, for_update=True
        )
        if current is None:
            raise CustomFieldDefinitionNotFoundError()

        row = await _field_repo.archive(
            conn, organization_id=organization_id, field_id=field_id, version=data.version
        )
        if row is None:
            raise CustomFieldDefinitionVersionConflictError()

        await record_audit_event(
            conn,
            organization_id=organization_id,
            actor_member_id=_actor_id(caller),
            action="custom_field_definition.archive",
            entity_type="custom_field_definition",
            entity_id=field_id,
            request_id=request_id,
            before_state=_field_dict(current),
            after_state=_field_dict(row),
        )
        await _outbox(
            conn,
            organization_id=organization_id,
            event_type=CUSTOM_FIELD_DEFINITION_ARCHIVED,
            aggregate_type="custom_field_definition",
            aggregate_id=field_id,
            payload={"id": str(field_id), "category_id": str(row["category_id"]), "key": row["key"]},
        )
    return CustomFieldDefinitionRead.model_validate(_field_dict(row))


# ==============================================================================
# Manufacturers and suppliers (identical behavior, distinct tables/errors/events)
# ==============================================================================


async def _list_reference(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    data_repo: repo.ReferenceDataRepository,
    read_cls: type[ManufacturerRead] | type[SupplierRead],
    status: str | None,
    after: str | None,
    limit: int,
) -> CursorPage:
    _require_read(caller)
    scope_filter = _list_scope_filter()
    cursor = repo.decode_cursor(after) if after else None
    async with tenant_transaction(pool, organization_id) as conn:
        rows = await data_repo.list_page(
            conn,
            organization_id=organization_id,
            scope_filter=scope_filter,
            status=status,
            after=cursor,
            limit=limit,
        )
    items = [read_cls.model_validate(_reference_dict(row)).model_dump(mode="json") for row in rows]
    next_cursor = repo.encode_cursor(rows[-1]["name"], rows[-1]["id"]) if len(rows) == limit else None
    return CursorPage(items=items, next_cursor=next_cursor)


def _reference_dict(row: Any) -> dict[str, Any]:
    out = dict(row)
    if isinstance(out.get("contact"), str):
        out["contact"] = json.loads(out["contact"])
    return out


async def _get_reference(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    data_repo: repo.ReferenceDataRepository,
    read_cls: type[ManufacturerRead] | type[SupplierRead],
    record_id: UUID,
    not_found_cls: type[ManufacturerNotFoundError] | type[SupplierNotFoundError],
) -> ManufacturerRead | SupplierRead:
    _require_read(caller)
    async with tenant_transaction(pool, organization_id) as conn:
        row = await data_repo.get_by_id(conn, organization_id=organization_id, record_id=record_id)
    if row is None:
        raise not_found_cls()
    return read_cls.model_validate(_reference_dict(row))


async def _create_reference(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    data_repo: repo.ReferenceDataRepository,
    read_cls: type[ManufacturerRead] | type[SupplierRead],
    data: ManufacturerCreate | SupplierCreate,
    conflict_cls: type[ManufacturerConflictError] | type[SupplierConflictError],
    entity_type: str,
    created_event: str,
    request_id: str | None,
) -> ManufacturerRead | SupplierRead:
    _require_write(caller)
    async with tenant_transaction(pool, organization_id) as conn:
        existing = await data_repo.get_by_name(conn, organization_id=organization_id, name=data.name)
        if existing is not None:
            raise conflict_cls(f"{entity_type.capitalize()} {data.name!r} already exists")

        record_id = uuid7()
        row = await data_repo.create(
            conn,
            record_id=record_id,
            organization_id=organization_id,
            code=data.code,
            name=data.name,
            contact=data.contact,
            notes=data.notes,
        )
        await record_audit_event(
            conn,
            organization_id=organization_id,
            actor_member_id=_actor_id(caller),
            action=f"{entity_type}.create",
            entity_type=entity_type,
            entity_id=record_id,
            request_id=request_id,
            after_state=_reference_dict(row),
        )
        await _outbox(
            conn,
            organization_id=organization_id,
            event_type=created_event,
            aggregate_type=entity_type,
            aggregate_id=record_id,
            payload={"id": str(record_id), "name": data.name},
        )
    return read_cls.model_validate(_reference_dict(row))


async def _update_reference(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    data_repo: repo.ReferenceDataRepository,
    read_cls: type[ManufacturerRead] | type[SupplierRead],
    record_id: UUID,
    data: ManufacturerUpdate | SupplierUpdate,
    not_found_cls: type[ManufacturerNotFoundError] | type[SupplierNotFoundError],
    version_conflict_cls: type[ManufacturerVersionConflictError] | type[SupplierVersionConflictError],
    entity_type: str,
    updated_event: str,
    request_id: str | None,
) -> ManufacturerRead | SupplierRead:
    _require_write(caller)
    async with tenant_transaction(pool, organization_id) as conn:
        current = await data_repo.get_by_id(
            conn, organization_id=organization_id, record_id=record_id, for_update=True
        )
        if current is None:
            raise not_found_cls()

        row = await data_repo.update(
            conn,
            organization_id=organization_id,
            record_id=record_id,
            version=data.version,
            name=data.name,
            contact=data.contact,
            notes=data.notes,
            clear_notes=data.clear_notes,
        )
        if row is None:
            raise version_conflict_cls()

        await record_audit_event(
            conn,
            organization_id=organization_id,
            actor_member_id=_actor_id(caller),
            action=f"{entity_type}.update",
            entity_type=entity_type,
            entity_id=record_id,
            request_id=request_id,
            before_state=_reference_dict(current),
            after_state=_reference_dict(row),
        )
        await _outbox(
            conn,
            organization_id=organization_id,
            event_type=updated_event,
            aggregate_type=entity_type,
            aggregate_id=record_id,
            payload={"id": str(record_id), "name": row["name"]},
        )
    return read_cls.model_validate(_reference_dict(row))


async def _archive_reference(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    data_repo: repo.ReferenceDataRepository,
    read_cls: type[ManufacturerRead] | type[SupplierRead],
    record_id: UUID,
    version: int,
    not_found_cls: type[ManufacturerNotFoundError] | type[SupplierNotFoundError],
    version_conflict_cls: type[ManufacturerVersionConflictError] | type[SupplierVersionConflictError],
    entity_type: str,
    archived_event: str,
    request_id: str | None,
) -> ManufacturerRead | SupplierRead:
    _require_write(caller)
    async with tenant_transaction(pool, organization_id) as conn:
        current = await data_repo.get_by_id(
            conn, organization_id=organization_id, record_id=record_id, for_update=True
        )
        if current is None:
            raise not_found_cls()

        row = await data_repo.archive(
            conn, organization_id=organization_id, record_id=record_id, version=version
        )
        if row is None:
            raise version_conflict_cls()

        await record_audit_event(
            conn,
            organization_id=organization_id,
            actor_member_id=_actor_id(caller),
            action=f"{entity_type}.archive",
            entity_type=entity_type,
            entity_id=record_id,
            request_id=request_id,
            before_state=_reference_dict(current),
            after_state=_reference_dict(row),
        )
        await _outbox(
            conn,
            organization_id=organization_id,
            event_type=archived_event,
            aggregate_type=entity_type,
            aggregate_id=record_id,
            payload={"id": str(record_id), "name": row["name"]},
        )
    return read_cls.model_validate(_reference_dict(row))


async def list_manufacturers(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    status: str | None = None,
    after: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
) -> CursorPage:
    return await _list_reference(
        pool,
        organization_id=organization_id,
        caller=caller,
        data_repo=_manufacturer_repo,
        read_cls=ManufacturerRead,
        status=status,
        after=after,
        limit=limit,
    )


async def get_manufacturer(
    pool: Pool, *, organization_id: UUID, caller: MemberContext, manufacturer_id: UUID
) -> ManufacturerRead:
    return cast(
        ManufacturerRead,
        await _get_reference(
            pool,
            organization_id=organization_id,
            caller=caller,
            data_repo=_manufacturer_repo,
            read_cls=ManufacturerRead,
            record_id=manufacturer_id,
            not_found_cls=ManufacturerNotFoundError,
        ),
    )


async def create_manufacturer(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    data: ManufacturerCreate,
    request_id: str | None = None,
) -> ManufacturerRead:
    return cast(
        ManufacturerRead,
        await _create_reference(
            pool,
            organization_id=organization_id,
            caller=caller,
            data_repo=_manufacturer_repo,
            read_cls=ManufacturerRead,
            data=data,
            conflict_cls=ManufacturerConflictError,
            entity_type="manufacturer",
            created_event=MANUFACTURER_CREATED,
            request_id=request_id,
        ),
    )


async def update_manufacturer(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    manufacturer_id: UUID,
    data: ManufacturerUpdate,
    request_id: str | None = None,
) -> ManufacturerRead:
    return cast(
        ManufacturerRead,
        await _update_reference(
            pool,
            organization_id=organization_id,
            caller=caller,
            data_repo=_manufacturer_repo,
            read_cls=ManufacturerRead,
            record_id=manufacturer_id,
            data=data,
            not_found_cls=ManufacturerNotFoundError,
            version_conflict_cls=ManufacturerVersionConflictError,
            entity_type="manufacturer",
            updated_event=MANUFACTURER_UPDATED,
            request_id=request_id,
        ),
    )


async def archive_manufacturer(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    manufacturer_id: UUID,
    data: ManufacturerArchive,
    request_id: str | None = None,
) -> ManufacturerRead:
    return cast(
        ManufacturerRead,
        await _archive_reference(
            pool,
            organization_id=organization_id,
            caller=caller,
            data_repo=_manufacturer_repo,
            read_cls=ManufacturerRead,
            record_id=manufacturer_id,
            version=data.version,
            not_found_cls=ManufacturerNotFoundError,
            version_conflict_cls=ManufacturerVersionConflictError,
            entity_type="manufacturer",
            archived_event=MANUFACTURER_ARCHIVED,
            request_id=request_id,
        ),
    )


async def list_suppliers(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    status: str | None = None,
    after: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
) -> CursorPage:
    return await _list_reference(
        pool,
        organization_id=organization_id,
        caller=caller,
        data_repo=_supplier_repo,
        read_cls=SupplierRead,
        status=status,
        after=after,
        limit=limit,
    )


async def get_supplier(
    pool: Pool, *, organization_id: UUID, caller: MemberContext, supplier_id: UUID
) -> SupplierRead:
    return cast(
        SupplierRead,
        await _get_reference(
            pool,
            organization_id=organization_id,
            caller=caller,
            data_repo=_supplier_repo,
            read_cls=SupplierRead,
            record_id=supplier_id,
            not_found_cls=SupplierNotFoundError,
        ),
    )


async def create_supplier(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    data: SupplierCreate,
    request_id: str | None = None,
) -> SupplierRead:
    return cast(
        SupplierRead,
        await _create_reference(
            pool,
            organization_id=organization_id,
            caller=caller,
            data_repo=_supplier_repo,
            read_cls=SupplierRead,
            data=data,
            conflict_cls=SupplierConflictError,
            entity_type="supplier",
            created_event=SUPPLIER_CREATED,
            request_id=request_id,
        ),
    )


async def update_supplier(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    supplier_id: UUID,
    data: SupplierUpdate,
    request_id: str | None = None,
) -> SupplierRead:
    return cast(
        SupplierRead,
        await _update_reference(
            pool,
            organization_id=organization_id,
            caller=caller,
            data_repo=_supplier_repo,
            read_cls=SupplierRead,
            record_id=supplier_id,
            data=data,
            not_found_cls=SupplierNotFoundError,
            version_conflict_cls=SupplierVersionConflictError,
            entity_type="supplier",
            updated_event=SUPPLIER_UPDATED,
            request_id=request_id,
        ),
    )


async def archive_supplier(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    supplier_id: UUID,
    data: SupplierArchive,
    request_id: str | None = None,
) -> SupplierRead:
    return cast(
        SupplierRead,
        await _archive_reference(
            pool,
            organization_id=organization_id,
            caller=caller,
            data_repo=_supplier_repo,
            read_cls=SupplierRead,
            record_id=supplier_id,
            version=data.version,
            not_found_cls=SupplierNotFoundError,
            version_conflict_cls=SupplierVersionConflictError,
            entity_type="supplier",
            archived_event=SUPPLIER_ARCHIVED,
            request_id=request_id,
        ),
    )


# ==============================================================================
# Template seed on module install (§B5.9, §B7.1, §B7.3 vs §B8.2 - see the plan's open point)
# ==============================================================================


@dataclass(frozen=True)
class SeedResult:
    domain_key: str
    categories_created: int
    custom_fields_created: int


def _domains_dir(config_base_dir: Path | None) -> Path:
    base = config_base_dir if config_base_dir is not None else resolve_config_path().parent
    return base / "domains"


def _load_template_categories(template_file: Path) -> list[Any]:
    """Every `assets.categories` entry of `template_file`, or `[]` for anything that keeps module
    install from working: a missing file, a broken template, or a malformed `assets` section (all
    caught by `config validate` / CI separately, never here)."""
    if not template_file.is_file():
        return []
    try:
        template = load_domain_template(template_file)
    except DomainTemplateError:
        return []
    extra = template.model_extra or {}
    assets_raw = extra.get("assets")
    if not isinstance(assets_raw, dict) or "categories" not in assets_raw:
        return []
    try:
        return list(parse_assets_section(assets_raw).categories)
    except Exception:  # noqa: BLE001 - malformed template never blocks module install
        return []


def _category_ready(category: Any, by_code: dict[str, Any], seeded_ids: dict[str, UUID]) -> bool:
    return (
        category.parent_code is None
        or category.parent_code in seeded_ids
        or category.parent_code not in by_code
    )


async def _seed_one_category(
    conn: Any,
    *,
    organization_id: UUID,
    category: Any,
    seeded_ids: dict[str, UUID],
    seeded_paths: dict[str, str],
) -> tuple[bool, int]:
    """Create `category`'s row (and its custom field definitions) if missing.

    Returns `(category_created, custom_fields_created)`: an existing category or field, found by
    `code` / `key`, is never overwritten (§B7.1).
    """
    existing = await _category_repo.get_by_code(conn, organization_id=organization_id, code=category.code)
    created = existing is None
    if existing is not None:
        seeded_ids[category.code] = existing["id"]
        seeded_paths[category.code] = existing["path"]
    else:
        parent_path = seeded_paths.get(category.parent_code) if category.parent_code else None
        parent_id = seeded_ids.get(category.parent_code) if category.parent_code else None
        label = repo.to_ltree_label(category.code)
        path = f"{parent_path}.{label}" if parent_path else label
        team_id = None
        if category.responsible_team_code:
            team_id = await conn.fetchval(
                "SELECT id FROM public.teams WHERE organization_id = $1 AND code = $2",
                organization_id,
                category.responsible_team_code,
            )
        category_id = uuid7()
        await _category_repo.create(
            conn,
            category_id=category_id,
            organization_id=organization_id,
            parent_id=parent_id,
            path=path,
            code=category.code,
            name=category.label,
            tag_prefix=category.tag_prefix,
            default_criticality=category.default_criticality,
            responsible_team_id=team_id,
        )
        seeded_ids[category.code] = category_id
        seeded_paths[category.code] = path

    category_db_id = seeded_ids[category.code]
    fields_created = 0
    for field in category.custom_fields:
        if await _seed_one_custom_field(
            conn, organization_id=organization_id, category_db_id=category_db_id, field=field
        ):
            fields_created += 1
    return created, fields_created


async def _seed_one_custom_field(
    conn: Any, *, organization_id: UUID, category_db_id: UUID, field: Any
) -> bool:
    """Create `field`'s definition row if this category does not already have one with its key."""
    existing_field = await _field_repo.get_by_key(
        conn, organization_id=organization_id, category_id=category_db_id, key=field.key
    )
    if existing_field is not None:
        return False
    rules = _build_rules(field.min, field.max, field.regex, field.options)
    await _field_repo.create(
        conn,
        field_id=uuid7(),
        organization_id=organization_id,
        category_id=category_db_id,
        key=field.key,
        label=field.label,
        field_type=field.type,
        is_required=field.required,
        rules=rules,
        is_unique=field.is_unique,
        is_encrypted=field.is_encrypted,
        position=0,
    )
    return True


async def _seed_categories_parent_first(
    conn: Any, *, organization_id: UUID, categories: list[Any]
) -> tuple[int, int]:
    """Seed every category, parents before children, so a child's path can extend its parent's.

    An orphaned `parent_code` (already flagged by `config validate`, never expected here) just
    stops the loop early rather than seeding the rest in the wrong order.
    """
    by_code = {c.code: c for c in categories}
    seeded_ids: dict[str, UUID] = {}
    seeded_paths: dict[str, str] = {}
    categories_created = 0
    custom_fields_created = 0

    remaining = list(categories)
    while remaining:
        progressed = False
        for category in list(remaining):
            if category.code in seeded_ids:
                remaining.remove(category)
                continue
            if not _category_ready(category, by_code, seeded_ids):
                continue
            remaining.remove(category)
            progressed = True

            category_created, fields_created = await _seed_one_category(
                conn,
                organization_id=organization_id,
                category=category,
                seeded_ids=seeded_ids,
                seeded_paths=seeded_paths,
            )
            if category_created:
                categories_created += 1
            custom_fields_created += fields_created
        if not progressed:
            break
    return categories_created, custom_fields_created


async def seed_assets_catalog(
    conn: Any,
    *,
    organization_id: UUID,
    domain_key: str,
    config_base_dir: Path | None = None,
    actor_member_id: UUID | None = None,
    request_id: str | None = None,
) -> SeedResult:
    """Copy the domain template's `assets.categories` (and their custom fields) into the
    organization's tables, idempotent by `code` / `key` (§B7.1 "definitions live in files,
    assignments live in the database"; §B5.9 module installation).

    A second call (re-install, or installing again after an admin has already edited categories)
    only adds rows that are still missing; it never overwrites an existing row, so an admin's own
    edit to a seeded category or field is never undone. Must run inside the caller's own write
    transaction (the module-install transaction), so the seed and the `module.install` audit event
    commit or roll back together.
    """
    template_file = _domains_dir(config_base_dir) / f"{domain_key}.yaml"
    categories = _load_template_categories(template_file)
    categories_created, custom_fields_created = await _seed_categories_parent_first(
        conn, organization_id=organization_id, categories=categories
    )
    await _record_seed_event(
        conn,
        organization_id=organization_id,
        domain_key=domain_key,
        categories_created=categories_created,
        custom_fields_created=custom_fields_created,
        actor_member_id=actor_member_id,
        request_id=request_id,
    )
    return SeedResult(
        domain_key=domain_key,
        categories_created=categories_created,
        custom_fields_created=custom_fields_created,
    )


async def _record_seed_event(
    conn: Any,
    *,
    organization_id: UUID,
    domain_key: str,
    categories_created: int,
    custom_fields_created: int,
    actor_member_id: UUID | None,
    request_id: str | None,
) -> None:
    await record_audit_event(
        conn,
        organization_id=organization_id,
        actor_member_id=actor_member_id,
        action="asset_category.seeded",
        entity_type="organization_module",
        entity_id=organization_id,
        request_id=request_id,
        after_state={
            "domain_key": domain_key,
            "categories_created": categories_created,
            "custom_fields_created": custom_fields_created,
        },
    )
    await _outbox(
        conn,
        organization_id=organization_id,
        event_type=ASSET_CATEGORY_SEEDED,
        aggregate_type="organization_module",
        aggregate_id=organization_id,
        payload={
            "domain_key": domain_key,
            "categories_created": categories_created,
            "custom_fields_created": custom_fields_created,
        },
    )
