# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Catalog reference-data Pydantic schemas (§B8.1, §C1.3, §C4.1, M2.1-T1/T2, P8-06)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "CategoryArchive",
    "CategoryCreate",
    "CategoryMove",
    "CategoryRead",
    "CategoryUpdate",
    "CustomFieldDefinitionArchive",
    "CustomFieldDefinitionCreate",
    "CustomFieldDefinitionRead",
    "CustomFieldDefinitionUpdate",
    "ManufacturerArchive",
    "ManufacturerCreate",
    "ManufacturerRead",
    "ManufacturerUpdate",
    "SupplierArchive",
    "SupplierCreate",
    "SupplierRead",
    "SupplierUpdate",
]

_CODE_RE = re.compile(r"^[a-z0-9_]+(-[a-z0-9_]+)*$", re.IGNORECASE)
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_PREFIX_RE = re.compile(r"^[A-Z][A-Z0-9]{0,9}$")

CustomFieldType = Literal["text", "number", "date", "boolean", "select", "multi_select", "json"]


def _validate_code(value: str) -> str:
    cleaned = value.strip().lower()
    if not cleaned:
        raise ValueError("code cannot be empty")
    if len(cleaned) > 64:
        raise ValueError("code cannot exceed 64 characters")
    if not _CODE_RE.match(cleaned):
        raise ValueError("code must contain only alphanumeric characters, underscores and hyphens")
    return cleaned


# ==============================================================================
# Asset categories
# ==============================================================================


class CategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(description="Unique business code for the category")
    name: str = Field(min_length=1, max_length=255, description="Display name of the category")
    parent_id: UUID | None = Field(default=None, description="Parent category ID (None if root)")
    tag_prefix: str | None = Field(default=None, description="Tag-format prefix override for this category")
    default_criticality: str | None = Field(default=None, description="Default criticality for new assets")
    responsible_team_id: UUID | None = Field(default=None, description="Team responsible for this category")

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        return _validate_code(v)

    @field_validator("tag_prefix")
    @classmethod
    def _prefix(cls, v: str | None) -> str | None:
        if v is not None and not _PREFIX_RE.match(v):
            raise ValueError(
                "tag_prefix must be 1-10 characters: capital letters and digits, starting with a letter"
            )
        return v


class CategoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    tag_prefix: str | None = Field(default=None, description="Set to null to clear the override")
    clear_tag_prefix: bool = Field(default=False, description="Explicitly clear the tag prefix override")
    default_criticality: str | None = None
    clear_default_criticality: bool = Field(default=False)
    responsible_team_id: UUID | None = None
    clear_responsible_team: bool = Field(default=False)
    version: int = Field(ge=1, description="Current record version for optimistic concurrency control")

    @field_validator("tag_prefix")
    @classmethod
    def _prefix(cls, v: str | None) -> str | None:
        if v is not None and not _PREFIX_RE.match(v):
            raise ValueError(
                "tag_prefix must be 1-10 characters: capital letters and digits, starting with a letter"
            )
        return v


class CategoryMove(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_parent_id: UUID = Field(description="Destination parent category ID")
    version: int = Field(ge=1, description="Current record version for optimistic concurrency control")


class CategoryArchive(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1, description="Current record version for optimistic concurrency control")


class CategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    parent_id: UUID | None
    path: str
    code: str
    name: str
    tag_prefix: str | None
    default_criticality: str | None
    responsible_team_id: UUID | None
    status: str
    version: int
    created_at: datetime
    updated_at: datetime


# ==============================================================================
# Custom field definitions
# ==============================================================================


class CustomFieldDefinitionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(description="Immutable field key, used in assets.custom_fields")
    label: str = Field(min_length=1, max_length=255)
    field_type: CustomFieldType
    is_required: bool = False
    min: float | None = None
    max: float | None = None
    regex: str | None = None
    options: list[str] = Field(default_factory=list)
    is_unique: bool = False
    is_encrypted: bool = False
    position: int = 0

    @field_validator("key")
    @classmethod
    def _key(cls, v: str) -> str:
        if not _KEY_RE.match(v):
            raise ValueError("key must be lowercase letters, digits and underscores, starting with a letter")
        return v


class CustomFieldDefinitionUpdate(BaseModel):
    """A partial update. `key` and `is_encrypted` are immutable after creation (§B8.1) and never
    appear here; `field_type` may change only while no asset has a value for this key yet."""

    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1, max_length=255)
    field_type: CustomFieldType | None = None
    is_required: bool | None = None
    min: float | None = None
    clear_min: bool = False
    max: float | None = None
    clear_max: bool = False
    regex: str | None = None
    clear_regex: bool = False
    options: list[str] | None = None
    is_unique: bool | None = None
    position: int | None = None
    version: int = Field(ge=1, description="Current record version for optimistic concurrency control")


class CustomFieldDefinitionArchive(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1, description="Current record version for optimistic concurrency control")


class CustomFieldDefinitionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    category_id: UUID
    key: str
    label: str
    field_type: str
    is_required: bool
    rules: dict[str, object]
    is_unique: bool
    is_encrypted: bool
    position: int
    status: str
    version: int
    created_at: datetime
    updated_at: datetime


# ==============================================================================
# Manufacturers and suppliers (identical shape)
# ==============================================================================


class ManufacturerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str | None = None
    name: str = Field(min_length=1, max_length=255)
    contact: dict[str, object] = Field(default_factory=dict)
    notes: str | None = None

    @field_validator("code")
    @classmethod
    def _code(cls, v: str | None) -> str | None:
        return None if v is None else _validate_code(v)


class ManufacturerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    contact: dict[str, object] | None = None
    notes: str | None = None
    clear_notes: bool = False
    version: int = Field(ge=1)


class ManufacturerArchive(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)


class ManufacturerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    code: str | None
    name: str
    contact: dict[str, object]
    notes: str | None
    status: str
    version: int
    created_at: datetime
    updated_at: datetime


class SupplierCreate(BaseModel):
    """Identical shape to `ManufacturerCreate` (§B8.1): a separate class, not a subclass, so the
    two are never structurally interchangeable at the type level (a `SupplierRead` is not a kind
    of `ManufacturerRead`, even though their fields match)."""

    model_config = ConfigDict(extra="forbid")

    code: str | None = None
    name: str = Field(min_length=1, max_length=255)
    contact: dict[str, object] = Field(default_factory=dict)
    notes: str | None = None

    @field_validator("code")
    @classmethod
    def _code(cls, v: str | None) -> str | None:
        return None if v is None else _validate_code(v)


class SupplierUpdate(BaseModel):
    """Identical shape to `ManufacturerUpdate` (§B8.1); see `SupplierCreate`."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    contact: dict[str, object] | None = None
    notes: str | None = None
    clear_notes: bool = False
    version: int = Field(ge=1)


class SupplierArchive(BaseModel):
    """Identical shape to `ManufacturerArchive` (§B8.1); see `SupplierCreate`."""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)


class SupplierRead(BaseModel):
    """Identical shape to `ManufacturerRead` (§B8.1); see `SupplierCreate`."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    code: str | None
    name: str
    contact: dict[str, object]
    notes: str | None
    status: str
    version: int
    created_at: datetime
    updated_at: datetime
