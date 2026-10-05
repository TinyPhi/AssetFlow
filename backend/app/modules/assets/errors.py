# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Asset error classes (§C1.5.1, §C4.5, M2.1-T2)."""

from __future__ import annotations

from typing import ClassVar

from app.core.problems import FieldError, ValidationFailedError

__all__ = ["CustomFieldValidationError"]


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
