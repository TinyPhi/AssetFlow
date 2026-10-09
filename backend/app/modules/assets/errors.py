# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Asset error classes (§C1.5.1, §C4.5, M2.1-T2, M2.1-T3)."""

from __future__ import annotations

from typing import ClassVar

from app.core.problems import ConflictError, FieldError, NotFoundError, ValidationFailedError

__all__ = [
    "AssetInvalidTransitionError",
    "AssetNotFoundError",
    "AssetSavedViewNameConflictError",
    "AssetSavedViewNotFoundError",
    "AssetSavedViewVersionConflictError",
    "AssetVersionConflictError",
    "CustomFieldValidationError",
    "TagConflictError",
    "TagInvalidError",
]


class CustomFieldValidationError(ValidationFailedError):
    """One or more custom field values fail their definition's type or rules (§B8.1, §B10)."""

    status_code = 422
    code: ClassVar[str] = "asset.custom_field_invalid"
    title: ClassVar[str] = "Custom field validation failed"
    default_detail: ClassVar[str] = "One or more custom field values are invalid. See errors for each field."
    description: ClassVar[str] = (
        "A custom field value did not match its definition's type or rules (required, min, max, "
        "regex, options, size), named an unknown field key, or violated the unique-in-organization "
        "rule. `errors` lists each field as `custom_fields.<key>`."
    )

    def __init__(self, errors: list[FieldError]) -> None:
        super().__init__(errors=errors)


class TagInvalidError(ValidationFailedError):
    """A supplied asset tag does not match the organization's tag format (M2.1-T3, §B7.3)."""

    status_code = 422
    code: ClassVar[str] = "asset.tag_invalid"
    title: ClassVar[str] = "Asset tag invalid"
    default_detail: ClassVar[str] = "The supplied tag does not match this organization's tag format."
    description: ClassVar[str] = (
        "A tag supplied with a create or import (rather than generated) did not match the "
        "organization's domain-template tag format or category tag-prefix override: wrong prefix, "
        "wrong separator, or a numeric part shorter than the configured digit count."
    )

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail)


class AssetNotFoundError(NotFoundError):
    """No asset with this id in caller scope (not found or outside scope answer the same, §C4.5)."""

    status_code = 404
    code: ClassVar[str] = "asset.not_found"
    title: ClassVar[str] = "Asset not found"
    default_detail: ClassVar[str] = "The requested asset does not exist."
    description: ClassVar[str] = (
        "The requested asset does not exist, or exists but is outside the caller's scope (both "
        "answer identically, §C4.5)."
    )


class AssetVersionConflictError(ConflictError):
    """Optimistic concurrency: the submitted `version` no longer matches the stored row."""

    status_code = 409
    code: ClassVar[str] = "asset.version_conflict"
    title: ClassVar[str] = "Asset version conflict"
    default_detail: ClassVar[str] = "The asset was modified by another request."
    description: ClassVar[str] = "The provided version does not match the current database version."


class AssetInvalidTransitionError(ConflictError):
    """A status change the organization's domain template does not allow right now (§B8.1, §C4.5).

    `reason_code` is one of `unknown_status`, `not_allowed`, `reason_required`,
    `condition_failed:<field>`, `reserved_for_module:<module>`.
    """

    status_code = 409
    code: ClassVar[str] = "asset.invalid_transition"
    title: ClassVar[str] = "Invalid status transition"
    default_detail: ClassVar[str] = "This status change is not allowed."
    description: ClassVar[str] = (
        "The requested status change is not allowed by the organization's domain template: the "
        "move is not declared, a reason is required, a condition on the asset does not hold (for "
        "example a holder is still set on a move to an ended status), the target status is unknown, "
        "or the target status is set only by another module. `detail` names the current status, the "
        "requested status and what to do."
    )

    def __init__(self, from_status: str, to_status: str, reason_code: str) -> None:
        self.from_status = from_status
        self.to_status = to_status
        self.reason_code = reason_code
        super().__init__(_transition_detail(from_status, to_status, reason_code))


def _transition_detail(from_status: str, to_status: str, reason_code: str) -> str:
    head = f'Cannot change the status from "{from_status}" to "{to_status}"'
    kind, _, arg = reason_code.partition(":")
    if kind == "unknown_status":
        return f"{head}: a status is not defined in this organization's template. Choose a listed status."
    if kind == "reason_required":
        return f"{head}: a reason is required. Send `reason` with the request."
    if kind == "reserved_for_module":
        return f'{head}: "{to_status}" is set only by the {arg} module. Use that module instead.'
    if kind == "condition_failed":
        return (
            f"{head}: the condition on `{arg}` does not hold. Fix that first (for example return "
            "the asset from its holder), then retry."
        )
    return f"{head}: the template does not allow it. Read the asset's transitions to see the allowed moves."


class TagConflictError(ConflictError):
    """A supplied asset tag is already used by another asset in the same organization (M2.1-T3)."""

    status_code = 409
    code: ClassVar[str] = "asset.tag_conflict"
    title: ClassVar[str] = "Asset tag already in use"
    default_detail: ClassVar[str] = "This tag is already used by another asset in this organization."
    description: ClassVar[str] = (
        "A supplied tag (from a reserved QR tag or an import row) is already used by another "
        "asset in the same organization. Tags generated by the organization's own sequence never "
        "collide; this only happens for a tag the caller supplies."
    )

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail)


class AssetSavedViewNotFoundError(NotFoundError):
    """No saved view with this id belongs to the caller (another member's view answers the same)."""

    status_code = 404
    code: ClassVar[str] = "asset_saved_view.not_found"
    title: ClassVar[str] = "Saved view not found"
    default_detail: ClassVar[str] = "The requested saved view does not exist."
    description: ClassVar[str] = (
        "The saved view does not exist, or belongs to another member; both answer identically "
        "because a view is private to the member who created it."
    )


class AssetSavedViewVersionConflictError(ConflictError):
    """Optimistic concurrency: the submitted `version` no longer matches the stored view."""

    status_code = 409
    code: ClassVar[str] = "asset_saved_view.version_conflict"
    title: ClassVar[str] = "Saved view version conflict"
    default_detail: ClassVar[str] = "The saved view was modified by another request."
    description: ClassVar[str] = "The provided version does not match the current stored version."


class AssetSavedViewNameConflictError(ConflictError):
    """The member already has a saved view with this name."""

    status_code = 409
    code: ClassVar[str] = "asset_saved_view.name_conflict"
    title: ClassVar[str] = "Saved view name already in use"
    default_detail: ClassVar[str] = "You already have a saved view with this name."
    description: ClassVar[str] = "View names are unique per member within an organization."
