# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Custom field validation (master M2.1-T2, §B8.1 Custom fields, §B10 Input validation).

Pure validation: no database, no I/O. `validate_custom_fields` checks an asset's submitted
`custom_fields` values against the `custom_field_definitions` rows of its category and returns the
cleaned values split into `plain` (goes straight into `assets.custom_fields`) and `to_encrypt`
(plaintext strings for the caller to send through the secrets provider before the write
transaction opens; see `app.modules.assets.sensitive`).

Every type is validated by its own function; unknown keys and missing required fields are
refused; `partial=True` skips the required check for a key the write does not touch (an edit that
changes only some fields).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.core.problems import FieldError, ValidationFailedError
from app.modules.assets.errors import CustomFieldValidationError

__all__ = [
    "CleanValues",
    "CustomFieldDefinition",
    "CustomFieldType",
    "refuse_encrypted_field_filter",
    "validate_custom_fields",
]

CustomFieldType = Literal["text", "number", "date", "boolean", "select", "multi_select", "json"]

#: Bounds a text value before it ever reaches `re.fullmatch`, regardless of its own min/max rule
#: (§B10): the regex-timeout defense is a bounded input length plus a cached, length-capped
#: pattern (`compile_field_regex`), not a separate timer.
MAX_TEXT_LENGTH = 10_000

#: A regex pattern over 200 characters is refused when the definition itself is saved (P8-07);
#: `compile_field_regex` enforces the same cap here so a value can never be checked against a
#: pattern the definition layer would have refused.
MAX_REGEX_PATTERN_LENGTH = 200

#: `json` field values: serialized size cap (§B8.1).
MAX_JSON_BYTES = 16 * 1024

type JsonValue = str | int | float | bool | list["JsonValue"] | dict[str, "JsonValue"] | None


@lru_cache(maxsize=256)
def compile_field_regex(pattern: str) -> re.Pattern[str]:
    """Compile a `text` field's `regex` rule once; refuses an over-long pattern (§B10, §B8.1)."""
    if len(pattern) > MAX_REGEX_PATTERN_LENGTH:
        raise ValueError(f"regex must be at most {MAX_REGEX_PATTERN_LENGTH} characters")
    return re.compile(pattern)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class CustomFieldDefinition(_Strict):
    """One row of `custom_field_definitions` (§B8.2), as `validate_custom_fields` needs it."""

    key: str
    label: str
    field_type: CustomFieldType
    is_required: bool = False
    rules: Mapping[str, object] = {}
    is_unique: bool = False
    is_encrypted: bool = False


@dataclass
class CleanValues:
    """The result of a successful validation, split by storage destination."""

    plain: dict[str, JsonValue] = field(default_factory=dict)
    to_encrypt: dict[str, str] = field(default_factory=dict)


def refuse_encrypted_field_filter(field_key: str, *, encrypted_keys: Collection[str], where: str) -> None:
    """Refuse a list filter or sort naming an encrypted custom field (§B8.1: never searched or filtered).

    `where` is the dotted location of the offending query parameter (for example
    `query.filter.custom_fields.ssn`); raises `ValidationFailedError` (422 `validation.invalid_field`).
    """
    if field_key in encrypted_keys:
        message = f'field "{field_key}" is encrypted and cannot be filtered or sorted'
        raise ValidationFailedError(errors=[FieldError(field=where, message=message)])


def validate_custom_fields(
    definitions: Sequence[CustomFieldDefinition],
    values: Mapping[str, object],
    *,
    partial: bool = False,
) -> CleanValues:
    """Validate `values` (an asset's submitted `custom_fields`) against `definitions`.

    Returns the cleaned values on success; raises `CustomFieldValidationError` (one `errors[]`
    entry per field, `field` = `custom_fields.<key>`) otherwise. `partial=True` is for an edit
    that only touches some fields: a required field absent from `values` is not an error, but a
    present value (including an explicit `None`) is still validated.
    """
    by_key = {d.key: d for d in definitions}
    errors: list[FieldError] = []
    clean = CleanValues()

    for key in values:
        if key not in by_key:
            errors.append(_error(key, f'unknown custom field "{key}"'))

    for definition in definitions:
        present = definition.key in values
        if not present:
            if definition.is_required and not partial:
                errors.append(_error(definition.key, "this field is required"))
            continue
        raw = values[definition.key]
        if raw is None:
            if definition.is_required:
                errors.append(_error(definition.key, "this field is required"))
            else:
                _store(clean, definition, None)
            continue
        try:
            cleaned = _validate_value(definition, raw)
        except _FieldError as exc:
            errors.append(_error(definition.key, exc.message))
            continue
        _store(clean, definition, cleaned)

    if errors:
        raise CustomFieldValidationError(errors)
    return clean


class _FieldError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def _error(key: str, message: str) -> FieldError:
    return FieldError(field=f"custom_fields.{key}", message=message)


def _store(clean: CleanValues, definition: CustomFieldDefinition, value: JsonValue) -> None:
    if definition.is_encrypted:
        if value is None:
            return
        clean.to_encrypt[definition.key] = json.dumps(value, separators=(",", ":"), sort_keys=True)
    else:
        clean.plain[definition.key] = value


def _validate_value(definition: CustomFieldDefinition, raw: object) -> JsonValue:
    validator = _VALIDATORS[definition.field_type]
    return validator(raw, definition.rules)


def _rule_number(rules: Mapping[str, object], name: str) -> Decimal | None:
    value = rules.get(name)
    if value is None:
        return None
    return Decimal(str(value))


def _rule_int(rules: Mapping[str, object], name: str) -> int | None:
    value = rules.get(name)
    return None if value is None else int(value)  # type: ignore[call-overload]


def _rule_str(rules: Mapping[str, object], name: str) -> str | None:
    value = rules.get(name)
    return None if value is None else str(value)


def _rule_options(rules: Mapping[str, object]) -> list[str]:
    options = rules.get("options") or []
    if not isinstance(options, list) or not all(isinstance(o, str) for o in options):
        raise _FieldError("this field's definition has no valid options")
    return options


def _validate_text(raw: object, rules: Mapping[str, object]) -> str:
    if not isinstance(raw, str):
        raise _FieldError("must be text")
    if len(raw) > MAX_TEXT_LENGTH:
        raise _FieldError(f"must be at most {MAX_TEXT_LENGTH} characters")
    min_len, max_len = _rule_int(rules, "min"), _rule_int(rules, "max")
    if min_len is not None and len(raw) < min_len:
        raise _FieldError(f"must be at least {min_len} characters")
    if max_len is not None and len(raw) > max_len:
        raise _FieldError(f"must be at most {max_len} characters")
    pattern = _rule_str(rules, "regex")
    if pattern is not None:
        try:
            compiled = compile_field_regex(pattern)
        except ValueError as exc:
            raise _FieldError("this field's definition has an invalid pattern") from exc
        if compiled.fullmatch(raw) is None:
            raise _FieldError("does not match the required pattern")
    return raw


def _validate_number(raw: object, rules: Mapping[str, object]) -> str:
    if isinstance(raw, bool) or not isinstance(raw, int | float | Decimal | str):
        raise _FieldError("must be a number")
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        raise _FieldError("must be a number") from exc
    min_value, max_value = _rule_number(rules, "min"), _rule_number(rules, "max")
    if min_value is not None and value < min_value:
        raise _FieldError(f"must be at least {min_value}")
    if max_value is not None and value > max_value:
        raise _FieldError(f"must be at most {max_value}")
    return str(value)


def _validate_date(raw: object, rules: Mapping[str, object]) -> str:
    if not isinstance(raw, str):
        raise _FieldError("must be an ISO 8601 date (YYYY-MM-DD)")
    try:
        value = date.fromisoformat(raw)
    except ValueError as exc:
        raise _FieldError("must be an ISO 8601 date (YYYY-MM-DD)") from exc
    min_raw, max_raw = _rule_str(rules, "min"), _rule_str(rules, "max")
    if min_raw is not None and value < date.fromisoformat(min_raw):
        raise _FieldError(f"must be on or after {min_raw}")
    if max_raw is not None and value > date.fromisoformat(max_raw):
        raise _FieldError(f"must be on or before {max_raw}")
    return value.isoformat()


def _validate_boolean(raw: object, rules: Mapping[str, object]) -> bool:
    if type(raw) is not bool:
        raise _FieldError("must be true or false")
    return raw


def _validate_select(raw: object, rules: Mapping[str, object]) -> str:
    if not isinstance(raw, str):
        raise _FieldError("must be one of the allowed options")
    options = _rule_options(rules)
    if raw not in options:
        raise _FieldError("must be one of the allowed options")
    return raw


def _validate_multi_select(raw: object, rules: Mapping[str, object]) -> JsonValue:
    if not isinstance(raw, list) or not all(isinstance(v, str) for v in raw):
        raise _FieldError("must be a list of options")
    options = _rule_options(rules)
    if any(v not in options for v in raw):
        raise _FieldError("must be one of the allowed options")
    if len(set(raw)) != len(raw):
        raise _FieldError("must not repeat an option")
    min_count, max_count = _rule_int(rules, "min"), _rule_int(rules, "max")
    if min_count is not None and len(raw) < min_count:
        raise _FieldError(f"must have at least {min_count} option(s)")
    if max_count is not None and len(raw) > max_count:
        raise _FieldError(f"must have at most {max_count} option(s)")
    return raw


def _validate_json(raw: object, rules: Mapping[str, object]) -> dict[str, JsonValue] | list[JsonValue]:
    if not isinstance(raw, dict | list):
        raise _FieldError("must be a JSON object or array")
    try:
        size = len(json.dumps(raw, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise _FieldError("must be JSON-serializable") from exc
    if size > MAX_JSON_BYTES:
        raise _FieldError(f"must be at most {MAX_JSON_BYTES} bytes serialized")
    return raw


type _Validator = Callable[[object, Mapping[str, object]], JsonValue]

_VALIDATORS: dict[CustomFieldType, _Validator] = {
    "text": _validate_text,
    "number": _validate_number,
    "date": _validate_date,
    "boolean": _validate_boolean,
    "select": _validate_select,
    "multi_select": _validate_multi_select,
    "json": _validate_json,
}
