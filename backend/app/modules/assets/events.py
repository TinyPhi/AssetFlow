# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Asset catalog domain event definitions (§B9.3, §C4.1, M2.1-T1/T2, P8-06)."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

__all__ = [
    "ASSET_CATEGORY_ARCHIVED",
    "ASSET_CATEGORY_CREATED",
    "ASSET_CATEGORY_MOVED",
    "ASSET_CATEGORY_SEEDED",
    "ASSET_CATEGORY_UPDATED",
    "CUSTOM_FIELD_DEFINITION_ARCHIVED",
    "CUSTOM_FIELD_DEFINITION_CREATED",
    "CUSTOM_FIELD_DEFINITION_UPDATED",
    "MANUFACTURER_ARCHIVED",
    "MANUFACTURER_CREATED",
    "MANUFACTURER_UPDATED",
    "SUPPLIER_ARCHIVED",
    "SUPPLIER_CREATED",
    "SUPPLIER_UPDATED",
    "AssetCategoryArchivedEvent",
    "AssetCategoryCreatedEvent",
    "AssetCategoryMovedEvent",
    "AssetCategorySeededEvent",
    "AssetCategoryUpdatedEvent",
    "CustomFieldDefinitionArchivedEvent",
    "CustomFieldDefinitionCreatedEvent",
    "CustomFieldDefinitionUpdatedEvent",
    "ManufacturerArchivedEvent",
    "ManufacturerCreatedEvent",
    "ManufacturerUpdatedEvent",
    "SupplierArchivedEvent",
    "SupplierCreatedEvent",
    "SupplierUpdatedEvent",
]

ASSET_CATEGORY_CREATED = "asset_category.created"
ASSET_CATEGORY_UPDATED = "asset_category.updated"
ASSET_CATEGORY_MOVED = "asset_category.moved"
ASSET_CATEGORY_ARCHIVED = "asset_category.archived"
ASSET_CATEGORY_SEEDED = "asset_category.seeded"

CUSTOM_FIELD_DEFINITION_CREATED = "custom_field_definition.created"
CUSTOM_FIELD_DEFINITION_UPDATED = "custom_field_definition.updated"
CUSTOM_FIELD_DEFINITION_ARCHIVED = "custom_field_definition.archived"

MANUFACTURER_CREATED = "manufacturer.created"
MANUFACTURER_UPDATED = "manufacturer.updated"
MANUFACTURER_ARCHIVED = "manufacturer.archived"

SUPPLIER_CREATED = "supplier.created"
SUPPLIER_UPDATED = "supplier.updated"
SUPPLIER_ARCHIVED = "supplier.archived"


class AssetCategoryCreatedEvent(BaseModel):
    id: UUID = Field(description="Created category ID")
    code: str = Field(description="Category code")
    path: str = Field(description="Materialized ltree path")
    parent_id: UUID | None = Field(description="Parent category ID")


class AssetCategoryUpdatedEvent(BaseModel):
    id: UUID = Field(description="Updated category ID")
    name: str = Field(description="Current category name")


class AssetCategoryMovedEvent(BaseModel):
    id: UUID = Field(description="Moved category ID")
    old_path: str = Field(description="Previous ltree path")
    new_path: str = Field(description="New ltree path")
    new_parent_id: UUID | None = Field(description="New parent category ID")


class AssetCategoryArchivedEvent(BaseModel):
    id: UUID = Field(description="Archived category ID")
    code: str = Field(description="Category code")


class AssetCategorySeededEvent(BaseModel):
    domain_key: str = Field(description="Domain template the seed came from")
    categories_created: int = Field(description="New category rows created by this seed")
    custom_fields_created: int = Field(description="New custom field definition rows created by this seed")


class CustomFieldDefinitionCreatedEvent(BaseModel):
    id: UUID = Field(description="Created field definition ID")
    category_id: UUID = Field(description="Owning category ID")
    key: str = Field(description="Field key")
    field_type: str = Field(description="Engine field type")


class CustomFieldDefinitionUpdatedEvent(BaseModel):
    id: UUID = Field(description="Updated field definition ID")
    category_id: UUID = Field(description="Owning category ID")
    key: str = Field(description="Field key")


class CustomFieldDefinitionArchivedEvent(BaseModel):
    id: UUID = Field(description="Archived field definition ID")
    category_id: UUID = Field(description="Owning category ID")
    key: str = Field(description="Field key")


class ManufacturerCreatedEvent(BaseModel):
    id: UUID = Field(description="Created manufacturer ID")
    name: str = Field(description="Manufacturer name")


class ManufacturerUpdatedEvent(BaseModel):
    id: UUID = Field(description="Updated manufacturer ID")
    name: str = Field(description="Current manufacturer name")


class ManufacturerArchivedEvent(BaseModel):
    id: UUID = Field(description="Archived manufacturer ID")
    name: str = Field(description="Manufacturer name")


class SupplierCreatedEvent(BaseModel):
    id: UUID = Field(description="Created supplier ID")
    name: str = Field(description="Supplier name")


class SupplierUpdatedEvent(BaseModel):
    id: UUID = Field(description="Updated supplier ID")
    name: str = Field(description="Current supplier name")


class SupplierArchivedEvent(BaseModel):
    id: UUID = Field(description="Archived supplier ID")
    name: str = Field(description="Supplier name")
