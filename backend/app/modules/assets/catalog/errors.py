# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Catalog reference-data error classes (§C1.5.1, §C4.5, M2.1-T1/T2)."""

from __future__ import annotations

from typing import ClassVar

from app.core.problems import ConflictError, NotFoundError

__all__ = [
    "CategoryArchiveBlockedError",
    "CategoryConflictError",
    "CategoryInvalidMoveError",
    "CategoryNotFoundError",
    "CategoryVersionConflictError",
    "CustomFieldDefinitionConflictError",
    "CustomFieldDefinitionNotFoundError",
    "CustomFieldDefinitionVersionConflictError",
    "CustomFieldTypeChangeBlockedError",
    "ManufacturerConflictError",
    "ManufacturerNotFoundError",
    "ManufacturerVersionConflictError",
    "SupplierConflictError",
    "SupplierNotFoundError",
    "SupplierVersionConflictError",
]


class CategoryNotFoundError(NotFoundError):
    status_code = 404
    code: ClassVar[str] = "asset_category.not_found"
    title: ClassVar[str] = "Asset category not found"
    default_detail: ClassVar[str] = "The requested asset category does not exist."
    description: ClassVar[str] = "The requested asset category does not exist within caller scope."


class CategoryConflictError(ConflictError):
    status_code = 409
    code: ClassVar[str] = "asset_category.conflict"
    title: ClassVar[str] = "Asset category conflict"
    default_detail: ClassVar[str] = "An asset category with this code already exists."
    description: ClassVar[str] = "An asset category unique constraint was violated."


class CategoryVersionConflictError(ConflictError):
    status_code = 409
    code: ClassVar[str] = "asset_category.version_conflict"
    title: ClassVar[str] = "Asset category version conflict"
    default_detail: ClassVar[str] = "The asset category was modified by another request."
    description: ClassVar[str] = "The provided version does not match the current database version."


class CategoryInvalidMoveError(ConflictError):
    status_code = 409
    code: ClassVar[str] = "asset_category.invalid_move"
    title: ClassVar[str] = "Invalid asset category move"
    default_detail: ClassVar[str] = "Cannot move an asset category into itself or its own descendants."
    description: ClassVar[str] = "The requested move would create a cycle or cross organization boundaries."


class CategoryArchiveBlockedError(ConflictError):
    status_code = 409
    code: ClassVar[str] = "asset_category.archive_blocked"
    title: ClassVar[str] = "Asset category archive blocked"
    default_detail: ClassVar[str] = "Cannot archive an asset category with active children or assets."
    description: ClassVar[str] = (
        "Archiving is blocked by active child categories or assets using this category."
    )


class CustomFieldDefinitionNotFoundError(NotFoundError):
    status_code = 404
    code: ClassVar[str] = "custom_field_definition.not_found"
    title: ClassVar[str] = "Custom field definition not found"
    default_detail: ClassVar[str] = "The requested custom field definition does not exist."
    description: ClassVar[str] = "The requested custom field definition does not exist within caller scope."


class CustomFieldDefinitionConflictError(ConflictError):
    status_code = 409
    code: ClassVar[str] = "custom_field_definition.conflict"
    title: ClassVar[str] = "Custom field definition conflict"
    default_detail: ClassVar[str] = "A custom field with this key already exists on this category."
    description: ClassVar[str] = "A custom field definition unique constraint was violated."


class CustomFieldDefinitionVersionConflictError(ConflictError):
    status_code = 409
    code: ClassVar[str] = "custom_field_definition.version_conflict"
    title: ClassVar[str] = "Custom field definition version conflict"
    default_detail: ClassVar[str] = "The custom field definition was modified by another request."
    description: ClassVar[str] = "The provided version does not match the current database version."


class CustomFieldTypeChangeBlockedError(ConflictError):
    status_code = 409
    code: ClassVar[str] = "custom_field_definition.type_change_blocked"
    title: ClassVar[str] = "Custom field type change blocked"
    default_detail: ClassVar[str] = "Cannot change the type of a field that already has values on an asset."
    description: ClassVar[str] = (
        "At least one asset already stores a value for this field key, so its type (and whether it "
        "is encrypted) can no longer change; archive the field and create a new one instead."
    )


class ManufacturerNotFoundError(NotFoundError):
    status_code = 404
    code: ClassVar[str] = "manufacturer.not_found"
    title: ClassVar[str] = "Manufacturer not found"
    default_detail: ClassVar[str] = "The requested manufacturer does not exist."
    description: ClassVar[str] = "The requested manufacturer does not exist within caller scope."


class ManufacturerConflictError(ConflictError):
    status_code = 409
    code: ClassVar[str] = "manufacturer.conflict"
    title: ClassVar[str] = "Manufacturer conflict"
    default_detail: ClassVar[str] = "A manufacturer with this name already exists."
    description: ClassVar[str] = "A manufacturer unique constraint was violated."


class ManufacturerVersionConflictError(ConflictError):
    status_code = 409
    code: ClassVar[str] = "manufacturer.version_conflict"
    title: ClassVar[str] = "Manufacturer version conflict"
    default_detail: ClassVar[str] = "The manufacturer was modified by another request."
    description: ClassVar[str] = "The provided version does not match the current database version."


class SupplierNotFoundError(NotFoundError):
    status_code = 404
    code: ClassVar[str] = "supplier.not_found"
    title: ClassVar[str] = "Supplier not found"
    default_detail: ClassVar[str] = "The requested supplier does not exist."
    description: ClassVar[str] = "The requested supplier does not exist within caller scope."


class SupplierConflictError(ConflictError):
    status_code = 409
    code: ClassVar[str] = "supplier.conflict"
    title: ClassVar[str] = "Supplier conflict"
    default_detail: ClassVar[str] = "A supplier with this name already exists."
    description: ClassVar[str] = "A supplier unique constraint was violated."


class SupplierVersionConflictError(ConflictError):
    status_code = 409
    code: ClassVar[str] = "supplier.version_conflict"
    title: ClassVar[str] = "Supplier version conflict"
    default_detail: ClassVar[str] = "The supplier was modified by another request."
    description: ClassVar[str] = "The provided version does not match the current database version."
