# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Asset service: create (§B8.1, §B5.3, §C4.2-§C4.4, M2.1-T5, P8-07).

Builds on primitives P8-04/P8-05/P8-06 already proved against the database: `validate_custom_fields`,
`encrypt_custom_fields`/`decrypt_custom_fields`, `lock_and_check_unique_custom_field`,
`assign_tag`/`validate_supplied_tag`, and the catalog module's category/field repositories (reading
another `app.modules.assets.*` submodule is not the cross-module import `.importlinter`'s
`repo-assets` contract forbids; that contract protects other modules, not this one from itself).

Record-level checks use `ScopeResolver.check_access` against `{"owner_org_unit_path": ...}`; a caller
with no `asset.create` grant at all is refused before any lookup (§C4.5: never probes existence).

Edit, detail and list are later parts of this plan, added to this same file (split to stay under the
repo's 800-changed-line PR guardrail: the whole feature does not fit in one PR).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

from app.core.config import resolve_config_path
from app.core.db import Pool, tenant_transaction
from app.core.ids import uuid7
from app.core.permissions import ScopeFilter
from app.core.problems import FieldError, PermissionDeniedError, ValidationFailedError
from app.core.scope import MemberContext, default_scope_resolver
from app.engines.automation.domain_template import DomainTemplateError, load_domain_template
from app.modules.assets import repository as repo
from app.modules.assets.catalog import repository as catalog_repo
from app.modules.assets.config import AssetsConfig, parse_assets_section
from app.modules.assets.custom_fields import (
    CleanValues,
    CustomFieldDefinition,
    JsonValue,
    validate_custom_fields,
)
from app.modules.assets.events import ASSET_CREATED
from app.modules.assets.permissions import CREATE_PERMISSION
from app.modules.assets.schemas import AssetCreate, AssetRead, HolderRead
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
    "create_asset",
]

READ_SENSITIVE_PERMISSION = "asset.read_sensitive"

_category_repo = catalog_repo.CategoryRepository()
_field_repo = catalog_repo.CustomFieldDefinitionRepository()
_asset_repo = repo.AssetRepository()


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


async def _to_asset_read(
    conn: Any,
    row: Any,
    *,
    organization_id: UUID,
    caller: MemberContext,
    secrets_provider: SecretsProvider,
) -> AssetRead:
    data = dict(row)
    custom_fields = _as_dict(data["custom_fields"])
    encrypted_raw = _as_dict(data["encrypted_fields"])
    encrypted_defs = await _field_definitions(
        conn, organization_id=organization_id, category_id=data["category_id"]
    )
    encrypted_keys = {d.key for d in encrypted_defs if d.is_encrypted}

    if default_scope_resolver.has_permission(caller, READ_SENSITIVE_PERMISSION) and encrypted_raw:
        decrypted: dict[str, JsonValue] = await decrypt_custom_fields(
            secrets_provider, organization_id=str(organization_id), ciphertexts=encrypted_raw
        )
        encrypted_view: dict[str, object] = dict(decrypted)
    else:
        encrypted_view = dict(encrypted_field_presence(encrypted_keys, encrypted_raw))

    if data.get("holder_type") == "member" and data.get("holder_id") is not None:
        departed = await _asset_repo.departed_member_ids(
            conn, organization_id=organization_id, member_ids=[data["holder_id"]]
        )
        _apply_departed_marker(data, departed)

    return AssetRead(
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
        version=data["version"],
        created_at=data["created_at"],
        updated_at=data["updated_at"],
    )


# ==============================================================================
# Create
# ==============================================================================


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
    if idempotency_key:
        async with tenant_transaction(pool, organization_id) as conn:
            existing = await _asset_repo.get_by_idempotency_key(
                conn, organization_id=organization_id, idempotency_key=idempotency_key
            )
            if existing is not None:
                detail = await _asset_repo.get_detail(
                    conn, organization_id=organization_id, asset_id=existing["id"]
                )
                assert detail is not None  # noqa: S101
                return await _to_asset_read(
                    conn,
                    detail,
                    organization_id=organization_id,
                    caller=caller,
                    secrets_provider=secrets_provider,
                )

    if not default_scope_resolver.has_permission(caller, CREATE_PERMISSION):
        # Fails closed before any lookup: a caller with no `asset.create` grant at all is refused
        # without probing whether the target org unit exists (never leaks that, §C4.5).
        raise PermissionDeniedError(f"Permission {CREATE_PERMISSION!r} denied.")

    async with tenant_transaction(pool, organization_id) as conn:
        owner_path = await _org_unit_path(conn, organization_id, data.owner_org_unit_id)
        if owner_path is None:
            raise ValidationFailedError(
                errors=[FieldError(field="owner_org_unit_id", message="not found or not active")]
            )
        if not default_scope_resolver.check_access(
            caller, CREATE_PERMISSION, {"owner_org_unit_path": owner_path}
        ):
            raise PermissionDeniedError(f"Permission {CREATE_PERMISSION!r} denied for this org unit.")

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

        definitions = await _field_definitions(
            conn, organization_id=organization_id, category_id=data.category_id
        )
        clean: CleanValues = validate_custom_fields(definitions, data.custom_fields)
        encrypted_fields = await encrypt_custom_fields(
            secrets_provider, organization_id=str(organization_id), plaintexts=clean.to_encrypt
        )

        domain_key = await _organization_domain_key(conn, organization_id)
        assets_config = _load_assets_config(domain_key, config_base_dir) if domain_key else None
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
            idempotency_key=idempotency_key,
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

        detail = await _asset_repo.get_detail(conn, organization_id=organization_id, asset_id=asset_id)
        assert detail is not None  # noqa: S101
        return await _to_asset_read(
            conn, detail, organization_id=organization_id, caller=caller, secrets_provider=secrets_provider
        )

