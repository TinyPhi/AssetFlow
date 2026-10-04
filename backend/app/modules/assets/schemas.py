# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Asset API Pydantic schemas (§B8.1, §B4.5, §C1.3, §C4.1, M2.1-T5, P8-07).

`AssetCreate`/`AssetUpdate` never accept `status`, `holder_*` or `tag` (status moves through P8-08,
holder through P9 custody, tag is never user-settable after create); `extra="forbid"` means a caller
naming any of those fields gets a plain 422 `validation.invalid_field`, satisfying the plan's "edit
with forbidden fields refused" without a bespoke error class.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "AssetCreate",
    "AssetListItem",
    "AssetListPage",
    "AssetRead",
    "AssetStatusChange",
    "AssetUpdate",
    "HolderRead",
    "TransitionRead",
]

HolderType = Literal["member", "team", "location"]


class AssetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    category_id: UUID
    model: str | None = Field(default=None, max_length=255)
    manufacturer_id: UUID | None = None
    supplier_id: UUID | None = None
    serial_number: str | None = Field(default=None, max_length=255)
    owner_org_unit_id: UUID
    location_id: UUID | None = None
    criticality: str | None = Field(default=None, description="Defaults to the category's own default")
    purchase_date: date | None = None
    purchase_cost: Decimal | None = Field(default=None, ge=0)
    warranty_end: date | None = None
    custom_fields: dict[str, object] = Field(default_factory=dict)
    notes: str | None = None
    tag: str | None = Field(
        default=None,
        description="Supply only for a reserved QR tag or an import row; otherwise generated (§B7.3)",
    )


class AssetUpdate(BaseModel):
    """A partial update. Unset fields are left unchanged; `version` is mandatory (§C4.3)."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    category_id: UUID | None = None
    model: str | None = Field(default=None, max_length=255)
    clear_model: bool = False
    manufacturer_id: UUID | None = None
    clear_manufacturer: bool = False
    supplier_id: UUID | None = None
    clear_supplier: bool = False
    serial_number: str | None = Field(default=None, max_length=255)
    clear_serial_number: bool = False
    owner_org_unit_id: UUID | None = None
    location_id: UUID | None = None
    clear_location: bool = False
    criticality: str | None = None
    purchase_date: date | None = None
    clear_purchase_date: bool = False
    purchase_cost: Decimal | None = Field(default=None, ge=0)
    clear_purchase_cost: bool = False
    warranty_end: date | None = None
    clear_warranty_end: bool = False
    custom_fields: dict[str, object] | None = Field(
        default=None, description="Fields to set; partial - omitted keys are left untouched"
    )
    notes: str | None = None
    clear_notes: bool = False
    version: int = Field(ge=1, description="Current record version for optimistic concurrency control")


class HolderRead(BaseModel):
    """Never the holder's email (§C5.2); a departed member shows a neutral marker."""

    type: HolderType
    id: UUID
    display_name: str


class AssetRead(BaseModel):
    """Detail view: full field set. Encrypted fields are presence-only unless the caller holds
    `asset.read_sensitive` and the service has decrypted them (then they appear under the same
    keys, as their typed value, inside `encrypted_fields`)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    tag: str
    name: str
    category_id: UUID
    category_name: str
    model: str | None
    manufacturer_id: UUID | None
    manufacturer_name: str | None
    supplier_id: UUID | None
    supplier_name: str | None
    serial_number: str | None
    owner_org_unit_id: UUID
    owner_org_unit_name: str
    owner_org_unit_path: str
    location_id: UUID | None
    location_name: str | None
    holder: HolderRead | None
    status: str
    criticality: str | None
    purchase_date: date | None
    purchase_cost: Decimal | None
    warranty_end: date | None
    custom_fields: dict[str, object]
    encrypted_fields: dict[str, object]
    notes: str | None
    version: int
    created_at: datetime
    updated_at: datetime


class AssetListItem(BaseModel):
    """List view: no `notes`, no encrypted data at all (§B8.1, §C5.2)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    tag: str
    name: str
    category_id: UUID
    category_name: str
    model: str | None
    manufacturer_id: UUID | None
    manufacturer_name: str | None
    serial_number: str | None
    owner_org_unit_id: UUID
    owner_org_unit_name: str
    location_id: UUID | None
    location_name: str | None
    holder: HolderRead | None
    status: str
    criticality: str | None
    warranty_end: date | None
    purchase_date: date | None
    custom_fields: dict[str, object]
    version: int
    created_at: datetime
    updated_at: datetime


class AssetListPage(BaseModel):
    items: list[AssetListItem]
    next_cursor: str | None
    total: int | None = Field(default=None, description="Only present when `include_total` was set")


class AssetStatusChange(BaseModel):
    """Body of `POST /assets/{id}/change-status` (§B8.1, P8-08)."""

    model_config = ConfigDict(extra="forbid")

    to_status: str = Field(min_length=1, max_length=64)
    version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=2000)


class TransitionRead(BaseModel):
    """One status change the caller may take now (for the UI's status menu; the API still decides)."""

    to_status: str
    to_label: str
    requires_reason: bool
