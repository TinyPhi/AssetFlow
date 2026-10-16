# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Asset service: create, edit, detail, list (§B8.1, §B5.3, §C4.2-§C4.4, M2.1-T5, P8-07).

Builds on primitives P8-04/P8-05/P8-06 already proved against the database: `validate_custom_fields`,
`encrypt_custom_fields`/`decrypt_custom_fields`, `lock_and_check_unique_custom_field`,
`assign_tag`/`validate_supplied_tag`, and the catalog module's category/field repositories (reading
another `app.modules.assets.*` submodule is not the cross-module import `.importlinter`'s
`repo-assets` contract forbids; that contract protects other modules, not this one from itself).

Record-level checks use `ScopeResolver.check_access` against `{"owner_org_unit_path": ...}`; a caller
with no `asset.create` grant at all is refused before any lookup (§C4.5: never probes existence).

List uses `ScopeResolver.resolve_scope_filter` instead of a per-record check, since a list has no
single record to check against (§B5.3): the repository builds the id set as a `UNION` of the
org-unit-path, team and self scope branches.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg

from app.core.config import resolve_config_path
from app.core.db import Pool, tenant_transaction
from app.core.ids import uuid7
from app.core.permissions import ScopeFilter
from app.core.problems import FieldError, PermissionDeniedError, ScopeDeniedError, ValidationFailedError
from app.core.scope import MemberContext, default_scope_resolver
from app.engines.automation.domain_template import DomainTemplateError, load_domain_template
from app.modules.assets import repository as repo
from app.modules.assets.access import require_in_scope
from app.modules.assets.catalog import repository as catalog_repo
from app.modules.assets.components import cascade
from app.modules.assets.components.repository import ComponentRepository
from app.modules.assets.config import STATUS_CATEGORIES, AssetsConfig, parse_assets_section
from app.modules.assets.custom_fields import (
    CleanValues,
    CustomFieldDefinition,
    JsonValue,
    refuse_encrypted_field_filter,
    validate_custom_fields,
)
from app.modules.assets.errors import (
    AssetInvalidTransitionError,
    AssetNotFoundError,
    AssetVersionConflictError,
)
from app.modules.assets.events import ASSET_CREATED, ASSET_STATUS_CHANGED, ASSET_UPDATED
from app.modules.assets.lifecycle import (
    AssetSnapshot,
    allowed_transitions,
    check_transition,
    find_transition,
)
from app.modules.assets.permissions import (
    CREATE_PERMISSION,
    READ_PERMISSION,
    RETIRE_PERMISSION,
    UPDATE_PERMISSION,
)
from app.modules.assets.schemas import (
    AssetCreate,
    AssetRead,
    AssetUpdate,
    HolderRead,
    ParentRead,
    StatusRead,
    TransitionRead,
    VocabularyRead,
)
from app.modules.assets.sensitive import (
    decrypt_custom_fields,
    encrypt_custom_fields,
    encrypted_field_presence,
)
from app.modules.assets.tags import assign_tag, validate_supplied_tag
from app.modules.assets.uniqueness import lock_and_check_unique_custom_field
from app.modules.audit.service import record_audit_event
from app.providers.secrets.base import SecretsProvider

__all__ = [
    "READ_SENSITIVE_PERMISSION",
    "AssetListResult",
    "change_status",
    "create_asset",
    "ended_statuses",
    "get_asset",
    "get_vocabulary",
    "list_assets",
    "list_transitions",
    "update_asset",
]

READ_SENSITIVE_PERMISSION = "asset.read_sensitive"

_category_repo = catalog_repo.CategoryRepository()
_field_repo = catalog_repo.CustomFieldDefinitionRepository()
_asset_repo = repo.AssetRepository()
_component_repo = ComponentRepository()


def _as_dict(value: Any) -> dict[str, Any]:
    return json.loads(value) if isinstance(value, str) else dict(value)


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


def _resource(row: Any) -> dict[str, Any]:
    holder_type = row["holder_type"]
    return {
        "owner_org_unit_path": row["owner_org_unit_path"],
        "team_id": str(row["holder_id"]) if holder_type == "team" and row["holder_id"] else None,
        "holder_member_id": str(row["holder_id"]) if holder_type == "member" and row["holder_id"] else None,
    }


def _require_read_detail(caller: MemberContext, row: Any) -> None:
    if not default_scope_resolver.check_access(caller, READ_PERMISSION, _resource(row)):
        raise AssetNotFoundError()


def _require_just_written(detail: Any) -> Any:
    """`get_detail` immediately after this same transaction wrote the row: `None` here is an
    invariant violation, not a normal "not found" (a plain `assert` would vanish under `-O`)."""
    if detail is None:
        raise RuntimeError("asset row vanished immediately after its own write")
    return detail


# ==============================================================================
# Domain template helpers (tag format, initial status - category defaults live in the DB row)
# ==============================================================================


def _domains_dir(config_base_dir: Path | None) -> Path:
    base = config_base_dir if config_base_dir is not None else resolve_config_path().parent
    return base / "domains"


def _load_assets_config(domain_key: str, config_base_dir: Path | None) -> AssetsConfig | None:
    template_file = _domains_dir(config_base_dir) / f"{domain_key}.yaml"
    if not template_file.is_file():
        return None
    try:
        template = load_domain_template(template_file)
    except DomainTemplateError:
        return None
    extra = template.model_extra or {}
    assets_raw = extra.get("assets")
    if not isinstance(assets_raw, dict):
        return None
    try:
        return parse_assets_section(assets_raw)
    except Exception:  # noqa: BLE001 - malformed template is a config-validate concern, not here
        return None


async def _organization_domain_key(conn: Any, organization_id: UUID) -> str | None:
    value: str | None = await conn.fetchval(
        "SELECT domain_key FROM public.organizations WHERE id = $1", organization_id
    )
    return value


def _check_criticality(value: str | None, assets_config: AssetsConfig | None) -> None:
    """A criticality is text validated from config: it must be one of the template's levels. With no
    template there are no levels, so only an empty value is accepted."""
    if value is None:
        return
    levels = assets_config.criticality if assets_config is not None else []
    if value not in levels:
        raise ValidationFailedError(
            errors=[FieldError(field="criticality", message=f"unknown criticality {value!r}")]
        )


# ==============================================================================
# Reference lookups
# ==============================================================================


async def _org_unit_path(conn: Any, organization_id: UUID, org_unit_id: UUID) -> str | None:
    value = await conn.fetchval(
        "SELECT path::text FROM public.org_units "
        "WHERE organization_id = $1 AND id = $2 AND status = 'active'",
        organization_id,
        org_unit_id,
    )
    return value if isinstance(value, str) else None


async def _field_definitions(
    conn: Any, *, organization_id: UUID, category_id: UUID
) -> list[CustomFieldDefinition]:
    rows = await _field_repo.list_by_category(
        conn,
        organization_id=organization_id,
        scope_filter=ScopeFilter.all_organization(),
        category_id=category_id,
        status="active",
        limit=500,
    )
    out = []
    for row in rows:
        rules = json.loads(row["rules"]) if isinstance(row["rules"], str) else dict(row["rules"])
        out.append(
            CustomFieldDefinition(
                key=row["key"],
                label=row["label"],
                field_type=row["field_type"],
                is_required=row["is_required"],
                rules=rules,
                is_unique=row["is_unique"],
                is_encrypted=row["is_encrypted"],
            )
        )
    return out


async def _validate_references(
    conn: Any,
    *,
    organization_id: UUID,
    manufacturer_id: UUID | None,
    supplier_id: UUID | None,
    location_id: UUID | None,
) -> None:
    errors: list[FieldError] = []
    if manufacturer_id is not None:
        found = await conn.fetchval(
            "SELECT 1 FROM public.manufacturers WHERE organization_id = $1 AND id = $2",
            organization_id,
            manufacturer_id,
        )
        if not found:
            errors.append(FieldError(field="manufacturer_id", message="not found"))
    if supplier_id is not None:
        found = await conn.fetchval(
            "SELECT 1 FROM public.suppliers WHERE organization_id = $1 AND id = $2",
            organization_id,
            supplier_id,
        )
        if not found:
            errors.append(FieldError(field="supplier_id", message="not found"))
    if location_id is not None:
        found = await conn.fetchval(
            "SELECT 1 FROM public.locations WHERE organization_id = $1 AND id = $2",
            organization_id,
            location_id,
        )
        if not found:
            errors.append(FieldError(field="location_id", message="not found"))
    if errors:
        raise ValidationFailedError(errors=errors)


# ==============================================================================
# Response assembly
# ==============================================================================


def _holder(row: Any) -> HolderRead | None:
    if row["holder_type"] is None:
        return None
    return HolderRead(type=row["holder_type"], id=row["holder_id"], display_name=row["holder_display_name"])


def _apply_departed_marker(row: dict[str, Any], departed: set[UUID]) -> None:
    if row.get("holder_type") == "member" and row.get("holder_id") in departed:
        row["holder_display_name"] = "Former member"


@dataclass(frozen=True)
class _PendingRead:
    """A read model built inside a transaction, with the ciphertexts it still has to decrypt.

    Decryption calls the secrets provider (OpenBao over the network in production), so it runs only
    after the transaction has closed: no pooled connection or row lock waits on it (§B8.1)."""

    read: AssetRead
    ciphertexts: dict[str, str]


async def _finish_read(
    pending: _PendingRead, *, organization_id: UUID, secrets_provider: SecretsProvider
) -> AssetRead:
    """Decrypt the pending ciphertexts in one batch, outside any transaction."""
    if not pending.ciphertexts:
        return pending.read
    decrypted: dict[str, JsonValue] = await decrypt_custom_fields(
        secrets_provider, organization_id=str(organization_id), ciphertexts=pending.ciphertexts
    )
    return pending.read.model_copy(update={"encrypted_fields": dict(decrypted)})


async def _to_asset_read(
    conn: Any,
    row: Any,
    *,
    organization_id: UUID,
    caller: MemberContext,
) -> _PendingRead:
    """The read model of `row`. Encrypted values the caller may read are left for `_finish_read`."""
    data = dict(row)
    custom_fields = _as_dict(data["custom_fields"])
    encrypted_raw = _as_dict(data["encrypted_fields"])
    encrypted_defs = await _field_definitions(
        conn, organization_id=organization_id, category_id=data["category_id"]
    )
    encrypted_keys = {d.key for d in encrypted_defs if d.is_encrypted}

    ciphertexts: dict[str, str] = {}
    if (
        default_scope_resolver.check_access(caller, READ_SENSITIVE_PERMISSION, _resource(row))
        and encrypted_raw
    ):
        ciphertexts = dict(encrypted_raw)
        encrypted_view: dict[str, object] = {}
    else:
        encrypted_view = dict(encrypted_field_presence(encrypted_keys, encrypted_raw))

    if data.get("holder_type") == "member" and data.get("holder_id") is not None:
        departed = await _asset_repo.departed_member_ids(
            conn, organization_id=organization_id, member_ids=[data["holder_id"]]
        )
        _apply_departed_marker(data, departed)

    parent, component_count = await _component_view(
        conn, organization_id=organization_id, caller=caller, asset_id=data["id"]
    )

    read = AssetRead(
        id=data["id"],
        organization_id=data["organization_id"],
        tag=data["tag"],
        name=data["name"],
        category_id=data["category_id"],
        category_name=data["category_name"],
        model=data["model"],
        manufacturer_id=data["manufacturer_id"],
        manufacturer_name=data["manufacturer_name"],
        supplier_id=data["supplier_id"],
        supplier_name=data["supplier_name"],
        serial_number=data["serial_number"],
        owner_org_unit_id=data["owner_org_unit_id"],
        owner_org_unit_name=data["owner_org_unit_name"],
        owner_org_unit_path=data["owner_org_unit_path"],
        location_id=data["location_id"],
        location_name=data["location_name"],
        holder=_holder(data),
        status=data["status"],
        criticality=data["criticality"],
        purchase_date=data["purchase_date"],
        purchase_cost=data["purchase_cost"],
        warranty_end=data["warranty_end"],
        custom_fields=custom_fields,
        encrypted_fields=encrypted_view,
        notes=data["notes"],
        parent=parent,
        component_count=component_count,
        version=data["version"],
        created_at=data["created_at"],
        updated_at=data["updated_at"],
    )
    return _PendingRead(read=read, ciphertexts=ciphertexts)


async def _component_view(
    conn: Any, *, organization_id: UUID, caller: MemberContext, asset_id: UUID
) -> tuple[ParentRead | None, int]:
    """The current parent (only when the caller may read it, §C4.5) and the child count."""
    parent_row = await _component_repo.get_parent_summary(
        conn, organization_id=organization_id, child_asset_id=asset_id
    )
    parent: ParentRead | None = None
    if parent_row is not None and default_scope_resolver.check_access(
        caller,
        READ_PERMISSION,
        {
            "owner_org_unit_path": parent_row["owner_org_unit_path"],
            "team_id": str(parent_row["holder_team_id"]) if parent_row["holder_team_id"] else None,
            "holder_member_id": str(parent_row["holder_member_id"])
            if parent_row["holder_member_id"]
            else None,
        },
    ):
        parent = ParentRead(id=parent_row["id"], tag=parent_row["tag"], name=parent_row["name"])
    count = await _component_repo.count_children(
        conn, organization_id=organization_id, parent_asset_id=asset_id
    )
    return parent, count


# ==============================================================================
# Create
# ==============================================================================


#: `Idempotency-Key` header: 1-255 visible ASCII characters. Bounded so an over-long key is a clean
#: 422, not a B-tree index-row overflow (500).
MAX_IDEMPOTENCY_KEY_LENGTH = 255


def _check_idempotency_key(key: str) -> None:
    if not 0 < len(key) <= MAX_IDEMPOTENCY_KEY_LENGTH or not all("!" <= ch <= "~" for ch in key):
        raise ValidationFailedError(
            errors=[
                FieldError(
                    field="Idempotency-Key",
                    message=f"must be 1 to {MAX_IDEMPOTENCY_KEY_LENGTH} visible ASCII characters",
                )
            ]
        )


def _same_create_request(existing: Any, data: AssetCreate) -> bool:
    """A replay must repeat the request that created the asset: same name, category and owner unit,
    and the same tag when one was supplied. A key reused for another asset is refused (422)."""
    same = (
        existing["name"] == data.name
        and existing["category_id"] == data.category_id
        and existing["owner_org_unit_id"] == data.owner_org_unit_id
    )
    return same and (data.tag is None or existing["tag"] == data.tag)


async def _replay_create(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    secrets_provider: SecretsProvider,
    data: AssetCreate,
    idempotency_key: str,
) -> AssetRead | None:
    """The asset this caller's earlier create with this `Idempotency-Key` made, or None for a new
    request. A key belongs to the member who sent it: another member's key never matches."""
    _check_idempotency_key(idempotency_key)
    member_id = _actor_id(caller)
    if member_id is None:
        return None
    pending: _PendingRead | None = None
    async with tenant_transaction(pool, organization_id) as conn:
        existing = await _asset_repo.get_by_idempotency_key(
            conn, organization_id=organization_id, member_id=member_id, idempotency_key=idempotency_key
        )
        if existing is not None:
            # A replay returns the stored asset only to a caller who may read it (else 404, so a
            # key never works as a bearer token, §C4.5), and only for the same request.
            if not default_scope_resolver.check_access(caller, READ_PERMISSION, _current_resource(existing)):
                raise AssetNotFoundError()
            if not _same_create_request(existing, data):
                raise ValidationFailedError(
                    "This Idempotency-Key was already used for a different request.",
                    errors=[
                        FieldError(field="Idempotency-Key", message="already used for a different request")
                    ],
                )
            detail = _require_just_written(
                await _asset_repo.get_detail(conn, organization_id=organization_id, asset_id=existing["id"])
            )
            pending = await _to_asset_read(conn, detail, organization_id=organization_id, caller=caller)
    if pending is None:
        return None
    return await _finish_read(pending, organization_id=organization_id, secrets_provider=secrets_provider)


async def create_asset(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    secrets_provider: SecretsProvider,
    data: AssetCreate,
    request_id: str | None = None,
    idempotency_key: str | None = None,
    config_base_dir: Path | None = None,
) -> AssetRead:
    if not default_scope_resolver.has_permission(caller, CREATE_PERMISSION):
        # Fails closed before any lookup, including the idempotency replay below: a caller with no
        # `asset.create` grant at all is refused without probing whether the key or org unit exists.
        raise PermissionDeniedError(f"Permission {CREATE_PERMISSION!r} denied.")

    if idempotency_key is not None:
        replayed = await _replay_create(
            pool,
            organization_id=organization_id,
            caller=caller,
            secrets_provider=secrets_provider,
            data=data,
            idempotency_key=idempotency_key,
        )
        if replayed is not None:
            return replayed
    try:
        return await _insert_new_asset(
            pool,
            organization_id=organization_id,
            caller=caller,
            secrets_provider=secrets_provider,
            data=data,
            request_id=request_id,
            idempotency_key=idempotency_key,
            config_base_dir=config_base_dir,
        )
    except asyncpg.UniqueViolationError as exc:
        # Two requests with the same key in flight at once: both found nothing to replay and both
        # inserted; the second hit the key's unique index (#360). Its transaction rolled back, so
        # replay the first request's asset instead of answering 500.
        if idempotency_key is None or exc.constraint_name != IDEMPOTENCY_UNIQUE_INDEX:
            raise
        replayed = await _replay_create(
            pool,
            organization_id=organization_id,
            caller=caller,
            secrets_provider=secrets_provider,
            data=data,
            idempotency_key=idempotency_key,
        )
        if replayed is None:
            raise
        return replayed


#: The unique index binding an `Idempotency-Key` to its member (migration 0019).
IDEMPOTENCY_UNIQUE_INDEX = "uq_assets__organization_id_idempotency_member_id_key"


async def _insert_new_asset(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    secrets_provider: SecretsProvider,
    data: AssetCreate,
    request_id: str | None,
    idempotency_key: str | None,
    config_base_dir: Path | None,
) -> AssetRead:
    """The create itself, in one transaction (the replay check has already run).

    Custom fields are validated and encrypted first, from a short read transaction, so the secrets
    provider is never called while the write transaction holds a connection or a lock (§B8.1)."""
    key_member_id = _actor_id(caller) if idempotency_key is not None else None

    async with tenant_transaction(pool, organization_id) as conn:
        definitions = await _field_definitions(
            conn, organization_id=organization_id, category_id=data.category_id
        )
    clean: CleanValues = validate_custom_fields(definitions, data.custom_fields)
    encrypted_fields = await encrypt_custom_fields(
        secrets_provider, organization_id=str(organization_id), plaintexts=clean.to_encrypt
    )

    async with tenant_transaction(pool, organization_id) as conn:
        owner_path = await _org_unit_path(conn, organization_id, data.owner_org_unit_id)
        if owner_path is None:
            raise ValidationFailedError(
                errors=[FieldError(field="owner_org_unit_id", message="not found or not active")]
            )
        if not default_scope_resolver.check_access(
            caller, CREATE_PERMISSION, {"owner_org_unit_path": owner_path}
        ):
            raise ScopeDeniedError(f"Permission {CREATE_PERMISSION!r} does not cover this org unit.")

        await _validate_references(
            conn,
            organization_id=organization_id,
            manufacturer_id=data.manufacturer_id,
            supplier_id=data.supplier_id,
            location_id=data.location_id,
        )

        category = await _category_repo.get_by_id(
            conn, organization_id=organization_id, category_id=data.category_id
        )
        if category is None:
            raise ValidationFailedError(errors=[FieldError(field="category_id", message="not found")])

        domain_key = await _organization_domain_key(conn, organization_id)
        assets_config = _load_assets_config(domain_key, config_base_dir) if domain_key else None
        _check_criticality(data.criticality, assets_config)
        initial_status = assets_config.initial if assets_config is not None else "active"
        tag_config = assets_config.tag if assets_config is not None else None

        criticality = data.criticality if data.criticality is not None else category["default_criticality"]
        category_prefix = category["tag_prefix"]

        asset_id = uuid7()

        unique_defs = [d for d in definitions if d.is_unique and d.key in clean.plain]
        for definition in unique_defs:
            value = clean.plain[definition.key]
            if value is not None:
                await lock_and_check_unique_custom_field(
                    conn,
                    organization_id=organization_id,
                    field_key=definition.key,
                    value=str(value),
                    asset_id=asset_id,
                )

        if data.tag is not None:
            if tag_config is None:
                raise ValidationFailedError(
                    errors=[FieldError(field="tag", message="no tag format configured")]
                )
            await validate_supplied_tag(conn, organization_id, tag_config, category_prefix, data.tag)
            tag = data.tag
        else:
            if tag_config is None:
                raise ValidationFailedError(
                    errors=[FieldError(field="tag", message="no tag format configured for this organization")]
                )
            tag = await assign_tag(conn, organization_id, tag_config, category_prefix)

        await _asset_repo.create(
            conn,
            asset_id=asset_id,
            organization_id=organization_id,
            tag=tag,
            name=data.name,
            category_id=data.category_id,
            model=data.model,
            manufacturer_id=data.manufacturer_id,
            supplier_id=data.supplier_id,
            serial_number=data.serial_number,
            owner_org_unit_id=data.owner_org_unit_id,
            location_id=data.location_id,
            status=initial_status,
            criticality=criticality,
            purchase_date=data.purchase_date,
            purchase_cost=data.purchase_cost,
            warranty_end=data.warranty_end,
            custom_fields=clean.plain,
            encrypted_fields=encrypted_fields,
            notes=data.notes,
            # Stored only with the member it belongs to (0019 CHECK): no member, no key.
            idempotency_key=idempotency_key if key_member_id is not None else None,
            idempotency_member_id=key_member_id,
        )

        await record_audit_event(
            conn,
            organization_id=organization_id,
            actor_member_id=_actor_id(caller),
            action="asset.create",
            entity_type="asset",
            entity_id=asset_id,
            request_id=request_id,
            after_state={"id": str(asset_id), "tag": tag, "category_id": str(data.category_id)},
        )
        await _outbox(
            conn,
            organization_id=organization_id,
            event_type=ASSET_CREATED,
            aggregate_type="asset",
            aggregate_id=asset_id,
            payload={
                "id": str(asset_id),
                "tag": tag,
                "category_id": str(data.category_id),
                "owner_org_unit_id": str(data.owner_org_unit_id),
            },
        )

        detail = _require_just_written(
            await _asset_repo.get_detail(conn, organization_id=organization_id, asset_id=asset_id)
        )
        pending = await _to_asset_read(conn, detail, organization_id=organization_id, caller=caller)
    return await _finish_read(pending, organization_id=organization_id, secrets_provider=secrets_provider)


# ==============================================================================
# Edit
# ==============================================================================


_SIMPLE_FIELDS = (
    "name",
    "model",
    "manufacturer_id",
    "supplier_id",
    "serial_number",
    "location_id",
    "criticality",
    "purchase_date",
    "purchase_cost",
    "warranty_end",
    "notes",
)
_CLEAR_FIELDS = {
    "model": "clear_model",
    "manufacturer_id": "clear_manufacturer",
    "supplier_id": "clear_supplier",
    "serial_number": "clear_serial_number",
    "location_id": "clear_location",
    "purchase_date": "clear_purchase_date",
    "purchase_cost": "clear_purchase_cost",
    "warranty_end": "clear_warranty_end",
    "notes": "clear_notes",
}


def _current_resource(current: Any) -> dict[str, Any]:
    holder_type = "member" if current["holder_member_id"] else "team" if current["holder_team_id"] else None
    return {
        "owner_org_unit_path": current["owner_org_unit_path"],
        "team_id": str(current["holder_team_id"]) if holder_type == "team" else None,
        "holder_member_id": str(current["holder_member_id"]) if holder_type == "member" else None,
    }


async def _check_owner_unit_move(
    conn: Any,
    *,
    organization_id: UUID,
    caller: MemberContext,
    current: Any,
    new_owner_org_unit_id: UUID | None,
) -> None:
    """Moving `owner_org_unit_id` needs `asset.update` on both the old and the new org unit."""
    if new_owner_org_unit_id is None or new_owner_org_unit_id == current["owner_org_unit_id"]:
        return
    new_path = await _org_unit_path(conn, organization_id, new_owner_org_unit_id)
    if new_path is None:
        raise ValidationFailedError(
            errors=[FieldError(field="owner_org_unit_id", message="not found or not active")]
        )
    old_ok = default_scope_resolver.check_access(
        caller, UPDATE_PERMISSION, {"owner_org_unit_path": current["owner_org_unit_path"]}
    )
    new_ok = default_scope_resolver.check_access(caller, UPDATE_PERMISSION, {"owner_org_unit_path": new_path})
    if not (old_ok and new_ok):
        raise ScopeDeniedError(
            f"Permission {UPDATE_PERMISSION!r} is needed on both the current and the new org unit."
        )


def _build_simple_sets(data: AssetUpdate) -> dict[str, Any]:
    sets: dict[str, Any] = {}
    for field_name in _SIMPLE_FIELDS:
        value = getattr(data, field_name)
        clear_flag = _CLEAR_FIELDS.get(field_name)
        if clear_flag and getattr(data, clear_flag):
            sets[field_name] = None
        elif value is not None:
            sets[field_name] = value
    if data.category_id is not None:
        sets["category_id"] = data.category_id
    if data.owner_org_unit_id is not None:
        sets["owner_org_unit_id"] = data.owner_org_unit_id
    return sets


@dataclass(frozen=True)
class _PreparedCustomFields:
    """An edit's custom fields, validated and encrypted before its write transaction opened."""

    definitions: list[Any]
    clean: CleanValues
    new_ciphertexts: dict[str, str]


async def _prepare_custom_field_update(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    asset_id: UUID,
    data: AssetUpdate,
    secrets_provider: SecretsProvider,
) -> _PreparedCustomFields | None:
    """Validate and encrypt an edit's custom fields from a short read transaction, so the secrets
    provider is never called while the write transaction holds the asset's row lock (§B8.1).

    The values are checked against the category the edit leaves the asset in, read at
    `data.version`. If the asset has moved on since, the edit is a version conflict anyway, so it is
    refused here rather than checked against a category it may no longer have."""
    if data.custom_fields is None:
        return None
    async with tenant_transaction(pool, organization_id) as conn:
        current = await _asset_repo.get_by_id(conn, organization_id=organization_id, asset_id=asset_id)
        if current is None:
            raise AssetNotFoundError()
        require_in_scope(caller, UPDATE_PERMISSION, _current_resource(current))
        if current["version"] != data.version:
            raise AssetVersionConflictError()
        category_id = data.category_id if data.category_id is not None else current["category_id"]
        definitions = await _field_definitions(conn, organization_id=organization_id, category_id=category_id)
    clean = validate_custom_fields(definitions, data.custom_fields, partial=True)
    new_ciphertexts = await encrypt_custom_fields(
        secrets_provider, organization_id=str(organization_id), plaintexts=clean.to_encrypt
    )
    return _PreparedCustomFields(definitions=list(definitions), clean=clean, new_ciphertexts=new_ciphertexts)


async def _apply_custom_field_update(
    conn: Any,
    *,
    organization_id: UUID,
    asset_id: UUID,
    current: Any,
    prepared: _PreparedCustomFields | None,
    sets: dict[str, Any],
) -> None:
    if prepared is None:
        return
    definitions, clean, new_ciphertexts = prepared.definitions, prepared.clean, prepared.new_ciphertexts
    current_plain = _as_dict(current["custom_fields"])
    current_encrypted = _as_dict(current["encrypted_fields"])

    unique_defs = {d.key: d for d in definitions if d.is_unique}
    for key, value in clean.plain.items():
        definition = unique_defs.get(key)
        if definition is not None and value is not None:
            await lock_and_check_unique_custom_field(
                conn, organization_id=organization_id, field_key=key, value=str(value), asset_id=asset_id
            )

    sets["custom_fields"] = {**current_plain, **clean.plain}
    sets["encrypted_fields"] = {**current_encrypted, **new_ciphertexts}


# Never copied into an audit row: encrypted values are recorded by field name only (§B8.1), so the
# audit log holds no ciphertext that would outlive a re-key or the value's deletion.
_AUDIT_VALUE_EXCLUDED = ("custom_fields", "encrypted_fields")


def _update_audit_states(current: Any, sets: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Before/after audit states of an edit. Both sides leave out the custom field maps; encrypted
    fields appear only as the names that changed (`encrypted_fields_changed`)."""
    before_state = {
        key: str(value) if isinstance(value, UUID) else value
        for key, value in dict(current).items()
        if key in sets and key not in _AUDIT_VALUE_EXCLUDED
    }
    after_state = {
        key: str(value) if isinstance(value, UUID) else value
        for key, value in sets.items()
        if key not in _AUDIT_VALUE_EXCLUDED
    }
    if "encrypted_fields" in sets:
        after_state["encrypted_fields_changed"] = sorted(sets["encrypted_fields"].keys())
    return before_state, after_state


async def update_asset(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    secrets_provider: SecretsProvider,
    asset_id: UUID,
    data: AssetUpdate,
    request_id: str | None = None,
    config_base_dir: Path | None = None,
) -> AssetRead:
    prepared = await _prepare_custom_field_update(
        pool,
        organization_id=organization_id,
        caller=caller,
        asset_id=asset_id,
        data=data,
        secrets_provider=secrets_provider,
    )
    async with tenant_transaction(pool, organization_id) as conn:
        current = await _asset_repo.get_by_id(
            conn, organization_id=organization_id, asset_id=asset_id, for_update=True
        )
        if current is None:
            raise AssetNotFoundError()

        require_in_scope(caller, UPDATE_PERMISSION, _current_resource(current))

        await _check_owner_unit_move(
            conn,
            organization_id=organization_id,
            caller=caller,
            current=current,
            new_owner_org_unit_id=data.owner_org_unit_id,
        )
        await _validate_references(
            conn,
            organization_id=organization_id,
            manufacturer_id=data.manufacturer_id,
            supplier_id=data.supplier_id,
            location_id=data.location_id,
        )
        if data.category_id is not None:
            category = await _category_repo.get_by_id(
                conn, organization_id=organization_id, category_id=data.category_id
            )
            if category is None:
                raise ValidationFailedError(errors=[FieldError(field="category_id", message="not found")])

        if data.criticality is not None:
            domain_key = await _organization_domain_key(conn, organization_id)
            assets_config = _load_assets_config(domain_key, config_base_dir) if domain_key else None
            _check_criticality(data.criticality, assets_config)

        sets = _build_simple_sets(data)
        await _apply_custom_field_update(
            conn,
            organization_id=organization_id,
            asset_id=asset_id,
            current=current,
            prepared=prepared,
            sets=sets,
        )

        owner_changes = (
            data.owner_org_unit_id is not None and data.owner_org_unit_id != current["owner_org_unit_id"]
        )
        location_changes = (data.location_id is not None and data.location_id != current["location_id"]) or (
            data.clear_location and current["location_id"] is not None
        )

        before_state, after_state = _update_audit_states(current, sets)
        row = await _asset_repo.update(
            conn, organization_id=organization_id, asset_id=asset_id, version=data.version, sets=sets
        )
        if row is None:
            raise AssetVersionConflictError()

        await record_audit_event(
            conn,
            organization_id=organization_id,
            actor_member_id=_actor_id(caller),
            action="asset.update",
            entity_type="asset",
            entity_id=asset_id,
            request_id=request_id,
            before_state=before_state,
            after_state=after_state,
        )
        await _outbox(
            conn,
            organization_id=organization_id,
            event_type=ASSET_UPDATED,
            aggregate_type="asset",
            aggregate_id=asset_id,
            payload={"id": str(asset_id), "version": row["version"]},
        )

        if data.move_components and (owner_changes or location_changes):
            await cascade.move_descendants(
                conn,
                organization_id=organization_id,
                caller=caller,
                parent_asset_id=asset_id,
                new_owner_org_unit_id=data.owner_org_unit_id if owner_changes else None,
                set_location=location_changes,
                new_location_id=None if data.clear_location else data.location_id,
                request_id=request_id,
            )

        detail = _require_just_written(
            await _asset_repo.get_detail(conn, organization_id=organization_id, asset_id=asset_id)
        )
        pending = await _to_asset_read(conn, detail, organization_id=organization_id, caller=caller)
    return await _finish_read(pending, organization_id=organization_id, secrets_provider=secrets_provider)


# ==============================================================================
# Detail
# ==============================================================================


async def get_asset(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    secrets_provider: SecretsProvider,
    asset_id: UUID,
) -> AssetRead:
    async with tenant_transaction(pool, organization_id) as conn:
        row = await _asset_repo.get_detail(conn, organization_id=organization_id, asset_id=asset_id)
        if row is None:
            raise AssetNotFoundError()
        _require_read_detail(caller, row)
        pending = await _to_asset_read(conn, row, organization_id=organization_id, caller=caller)
    return await _finish_read(pending, organization_id=organization_id, secrets_provider=secrets_provider)


# ==============================================================================
# List
# ==============================================================================


@dataclass(frozen=True)
class AssetListResult:
    items: list[dict[str, Any]]
    next_cursor: str | None
    total: int | None


async def _statuses_of_category(conn: Any, organization_id: UUID, category: str) -> tuple[str, ...]:
    """Status keys of the organization's domain template that belong to a status category."""
    if category not in STATUS_CATEGORIES:
        raise ValidationFailedError(
            errors=[FieldError(field="query.status_category", message=f'unknown category "{category}"')]
        )
    domain_key = await _organization_domain_key(conn, organization_id)
    config = _load_assets_config(domain_key, None) if domain_key else None
    if config is None:
        return ()
    return tuple(st.key for st in config.statuses if st.category == category)


async def ended_statuses(conn: Any, organization_id: UUID) -> tuple[str, ...]:
    """Status keys of the `ended` category in the organization's domain template (none without one)."""
    return await _statuses_of_category(conn, organization_id, "ended")


async def _resolve_custom_field_filters(
    conn: Any, organization_id: UUID, raw: Sequence[tuple[str, str, str]]
) -> tuple[tuple[str, str, object, str], ...]:
    """Check each `cf.<key>` filter against the organization's definitions and type its value."""
    if not raw:
        return ()
    rows = await conn.fetch(
        "SELECT key, field_type, bool_or(is_encrypted) AS is_encrypted "
        "FROM public.custom_field_definitions WHERE organization_id = $1 GROUP BY key, field_type",
        organization_id,
    )
    known = {r["key"]: r["field_type"] for r in rows}
    encrypted = {r["key"] for r in rows if r["is_encrypted"]}
    out: list[tuple[str, str, object, str]] = []
    for key, op, value in raw:
        where = f"query.cf.{key}"
        refuse_encrypted_field_filter(key, encrypted_keys=encrypted, where=where)
        field_type = known.get(key)
        if field_type is None:
            raise ValidationFailedError(errors=[FieldError(field=where, message="unknown custom field")])
        if op != "eq" and field_type not in ("number", "date"):
            raise ValidationFailedError(
                errors=[FieldError(field=where, message=f'operator "{op}" needs a number or date field')]
            )
        try:
            typed: object = (
                Decimal(value)
                if field_type == "number"
                else date.fromisoformat(value)
                if field_type == "date"
                else value
            )
        except (InvalidOperation, ValueError) as exc:
            raise ValidationFailedError(
                errors=[FieldError(field=where, message=f"value does not match the {field_type} field type")]
            ) from exc
        out.append((key, op, typed, field_type))
    return tuple(out)


async def list_assets(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    query: repo.AssetQuery,
    custom_field_filters: Sequence[tuple[str, str, str]] = (),
    status_category: str | None = None,
    sort: str = "-created_at",
    after: str | None = None,
    limit: int = 50,
    include_total: bool = False,
) -> AssetListResult:
    limit = max(1, min(limit, 200))
    # A caller with no `asset.read` grant at all is refused (403); one who holds it but whose
    # grants cover nothing yet (e.g. a brand-new org-unit grant with no assets under it) gets an
    # ordinary empty page (200), not an error - these are different situations (§C4.5).
    default_scope_resolver.require(caller, READ_PERMISSION, None)
    scope_filter = default_scope_resolver.resolve_scope_filter(caller, READ_PERMISSION)
    if scope_filter.is_empty:
        return AssetListResult(items=[], next_cursor=None, total=0 if include_total else None)

    async with tenant_transaction(pool, organization_id) as conn:
        resolved = replace(
            query,
            custom_field_filters=await _resolve_custom_field_filters(
                conn, organization_id, custom_field_filters
            ),
        )
        if status_category is not None:
            keys = await _statuses_of_category(conn, organization_id, status_category)
            wanted = tuple(k for k in keys if not query.status or k in query.status)
            if not wanted:
                return AssetListResult(items=[], next_cursor=None, total=0 if include_total else None)
            resolved = replace(resolved, status=wanted)

        # One extra row tells whether another page exists (§C4.4), without a second count query.
        rows, total = await _asset_repo.list_assets(
            conn,
            organization_id=organization_id,
            scope_filter=scope_filter,
            query=resolved,
            sort=sort,
            after=after,
            limit=limit + 1,
            include_total=include_total,
        )
        has_more = len(rows) > limit
        rows = rows[:limit]

        member_ids = [
            r["holder_id"] for r in rows if r["holder_type"] == "member" and r["holder_id"] is not None
        ]
        departed = await _asset_repo.departed_member_ids(
            conn, organization_id=organization_id, member_ids=member_ids
        )

        items: list[dict[str, Any]] = []
        for record in rows:
            data = dict(record)
            data["custom_fields"] = _as_dict(data["custom_fields"])
            _apply_departed_marker(data, departed)
            data["holder"] = _holder(data)
            items.append(data)

    next_cursor = _next_cursor(items, sort=sort, has_more=has_more, has_search=bool(query.q))
    return AssetListResult(items=items, next_cursor=next_cursor, total=total)


def _next_cursor(items: list[dict[str, Any]], *, sort: str, has_more: bool, has_search: bool) -> str | None:
    if not has_more or not items:
        return None
    last = items[-1]
    if has_search:
        return repo.encode_cursor(str(last.get("search_rank")), last["id"])
    desc = sort.startswith("-")
    key = sort[1:] if desc else sort
    raw = last.get(key)
    if raw is None and key in repo.NULLABLE_SENTINELS:
        value = repo.NULLABLE_SENTINELS[key][1 if desc else 0]
    else:
        value = raw.isoformat() if isinstance(raw, date | datetime) else str(raw)
    return repo.encode_cursor(value, last["id"])


# ==============================================================================
# Lifecycle: status change and the transitions available now (§B8.1, §C4.3, P8-08)
# ==============================================================================


async def _lifecycle_context(
    conn: Any, organization_id: UUID, current: Any
) -> tuple[AssetsConfig | None, AssetSnapshot]:
    domain_key = await _organization_domain_key(conn, organization_id)
    template = _load_assets_config(domain_key, None) if domain_key else None
    category = await _category_repo.get_by_id(
        conn, organization_id=organization_id, category_id=current["category_id"]
    )
    holder_type, holder_id = (
        ("member", current["holder_member_id"])
        if current["holder_member_id"]
        else ("team", current["holder_team_id"])
        if current["holder_team_id"]
        else ("location", current["holder_location_id"])
        if current["holder_location_id"]
        else (None, None)
    )
    snapshot = AssetSnapshot(
        status=current["status"],
        criticality=current["criticality"],
        category_code=category["code"] if category is not None else None,
        holder_type=holder_type,
        holder_id=str(holder_id) if holder_id is not None else None,
        custom_fields=_as_dict(current["custom_fields"]),
    )
    return template, snapshot


def _transition_permission(template: AssetsConfig, from_status: str, to_status: str) -> str:
    """The transition's own permission, else `asset.retire` for an ended target, else `asset.update`."""
    transition = find_transition(template, from_status, to_status)
    if transition is not None and transition.permission is not None:
        return transition.permission
    target = template.status(to_status)
    return RETIRE_PERMISSION if target is not None and target.category == "ended" else UPDATE_PERMISSION


async def change_status(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    secrets_provider: SecretsProvider,
    asset_id: UUID,
    to_status: str,
    version: int,
    reason: str | None,
    request_id: str | None = None,
) -> AssetRead:
    async with tenant_transaction(pool, organization_id) as conn:
        current = await _asset_repo.get_by_id(
            conn, organization_id=organization_id, asset_id=asset_id, for_update=True
        )
        if current is None:
            raise AssetNotFoundError()
        template, snapshot = await _lifecycle_context(conn, organization_id, current)
        permission = (
            _transition_permission(template, current["status"], to_status)
            if template is not None
            else UPDATE_PERMISSION
        )
        # Permission and scope on the loaded record come before any answer about the transition,
        # so a caller outside scope learns nothing about the asset's status (§C4.3, §C4.5).
        require_in_scope(caller, permission, _current_resource(current))
        if template is None:
            raise AssetInvalidTransitionError(current["status"], to_status, "not_allowed")
        check_transition(template, snapshot, to_status, reason=reason)

        # Terminal statuses end custody (§B8.1): closing an open assignment joins this transaction
        # once P9's custody tables exist (P9-02). Until then the shipped `holder.is_set` rule makes
        # a final target with a holder impossible.
        row = await _asset_repo.update(
            conn,
            organization_id=organization_id,
            asset_id=asset_id,
            version=version,
            sets={"status": to_status},
        )
        if row is None:
            raise AssetVersionConflictError()

        clean_reason = reason.strip() if reason and reason.strip() else None
        await record_audit_event(
            conn,
            organization_id=organization_id,
            actor_member_id=_actor_id(caller),
            action="asset.status_changed",
            entity_type="asset",
            entity_id=asset_id,
            request_id=request_id,
            before_state={"status": current["status"]},
            after_state={"status": to_status, "reason": clean_reason},
        )
        await _outbox(
            conn,
            organization_id=organization_id,
            event_type=ASSET_STATUS_CHANGED,
            aggregate_type="asset",
            aggregate_id=asset_id,
            payload={
                "id": str(asset_id),
                "from_status": current["status"],
                "to_status": to_status,
                "reason": clean_reason,
                "version": row["version"],
            },
        )

        detail = _require_just_written(
            await _asset_repo.get_detail(conn, organization_id=organization_id, asset_id=asset_id)
        )
        pending = await _to_asset_read(conn, detail, organization_id=organization_id, caller=caller)
    return await _finish_read(pending, organization_id=organization_id, secrets_provider=secrets_provider)


async def list_transitions(
    pool: Pool, *, organization_id: UUID, caller: MemberContext, asset_id: UUID
) -> list[TransitionRead]:
    """The status changes the caller may take now: declared, permitted on this record, conditions
    met, not reserved for a module. A reason-required move is listed with `requires_reason`."""
    async with tenant_transaction(pool, organization_id) as conn:
        current = await _asset_repo.get_by_id(conn, organization_id=organization_id, asset_id=asset_id)
        if current is None:
            raise AssetNotFoundError()
        resource = _current_resource(current)
        if not default_scope_resolver.check_access(caller, READ_PERMISSION, resource):
            raise AssetNotFoundError()
        template, snapshot = await _lifecycle_context(conn, organization_id, current)
    # Computed from the snapshot read above, outside the transaction on purpose: this list is a
    # hint for the UI, not authoritative. `change_status` re-reads and re-validates under lock.
    if template is None:
        return []
    out: list[TransitionRead] = []
    for transition in allowed_transitions(template, current["status"]):
        permission = _transition_permission(template, current["status"], transition.to)
        if not default_scope_resolver.check_access(caller, permission, resource):
            continue
        try:
            check_transition(template, snapshot, transition.to, reason="-")
        except AssetInvalidTransitionError:
            continue
        target = template.status(transition.to)
        if target is None:  # validated at config load
            raise RuntimeError("transition target status missing from the domain template")
        out.append(
            TransitionRead(
                to_status=transition.to, to_label=target.label, requires_reason=transition.requires_reason
            )
        )
    return out


def vocabulary_of(template: AssetsConfig | None) -> VocabularyRead:
    """The statuses (key, label, category) and criticality levels of a template; empty without one."""
    if template is None:
        return VocabularyRead(statuses=[], criticality=[])
    return VocabularyRead(
        statuses=[StatusRead(key=s.key, label=s.label, category=s.category) for s in template.statuses],
        criticality=list(template.criticality),
    )


async def get_vocabulary(pool: Pool, *, organization_id: UUID, caller: MemberContext) -> VocabularyRead:
    """The organization's asset vocabulary. Any member who may read assets may read it (no record)."""
    if not default_scope_resolver.has_permission(caller, READ_PERMISSION):
        raise PermissionDeniedError()
    async with tenant_transaction(pool, organization_id) as conn:
        domain_key = await _organization_domain_key(conn, organization_id)
    template = _load_assets_config(domain_key, None) if domain_key else None
    return vocabulary_of(template)
