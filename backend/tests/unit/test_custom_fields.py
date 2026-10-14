# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Custom field validation (M2.1-T2, §B8.1, §B10): every type, valid and invalid, each rule."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core.problems import FieldError, ValidationFailedError
from app.modules.assets.custom_fields import (
    MAX_JSON_BYTES,
    MAX_TEXT_LENGTH,
    CleanValues,
    CustomFieldDefinition,
    refuse_encrypted_field_filter,
    validate_custom_fields,
)
from app.modules.assets.errors import CustomFieldValidationError


def _def(**kwargs: object) -> CustomFieldDefinition:
    base: dict[str, object] = {"key": "f", "label": "F", "field_type": "text"}
    base.update(kwargs)
    return CustomFieldDefinition.model_validate(base)


def _errors(exc_info: pytest.ExceptionInfo[CustomFieldValidationError]) -> list[FieldError]:
    value = exc_info.value.errors
    assert value is not None
    return value


# --------------------------------------------------------------------------------------- generic


def test_unknown_key_is_refused() -> None:
    with pytest.raises(CustomFieldValidationError) as exc:
        validate_custom_fields([_def(key="known")], {"other": "x"})
    assert _errors(exc)[0].field == "custom_fields.other"


def test_required_field_missing_is_refused() -> None:
    with pytest.raises(CustomFieldValidationError) as exc:
        validate_custom_fields([_def(is_required=True)], {})
    assert _errors(exc)[0].field == "custom_fields.f"


def test_required_field_explicit_null_is_refused() -> None:
    with pytest.raises(CustomFieldValidationError):
        validate_custom_fields([_def(is_required=True)], {"f": None})


def test_partial_edit_skips_missing_required_field() -> None:
    clean = validate_custom_fields([_def(is_required=True)], {}, partial=True)
    assert clean.plain == {}


def test_partial_edit_still_validates_a_present_value() -> None:
    with pytest.raises(CustomFieldValidationError):
        validate_custom_fields([_def(field_type="number")], {"f": "not-a-number"}, partial=True)


def test_optional_field_absent_is_fine() -> None:
    clean = validate_custom_fields([_def(is_required=False)], {})
    assert clean.plain == {} and clean.to_encrypt == {}


def test_optional_field_explicit_null_clears_it() -> None:
    # An explicit null is a deliberate "clear this field" (a partial edit distinguishes it from
    # the field being absent, which leaves the stored value untouched).
    clean = validate_custom_fields([_def(is_required=False)], {"f": None})
    assert clean.plain == {"f": None}


def test_two_bad_fields_each_get_their_own_error() -> None:
    defs = [_def(key="a", is_required=True), _def(key="b", field_type="number")]
    with pytest.raises(CustomFieldValidationError) as exc:
        validate_custom_fields(defs, {"b": "nope"})
    fields = {e.field for e in _errors(exc)}
    assert fields == {"custom_fields.a", "custom_fields.b"}


def test_encrypted_value_goes_to_to_encrypt_not_plain() -> None:
    clean = validate_custom_fields([_def(is_encrypted=True)], {"f": "secret-value"})
    assert clean.plain == {}
    assert clean.to_encrypt["f"] == '"secret-value"'


def test_encrypted_null_is_not_sent_for_encryption() -> None:
    clean = validate_custom_fields([_def(is_encrypted=True)], {"f": None})
    assert clean.to_encrypt == {} and clean.plain == {}


# ------------------------------------------------------------------------------------------ text


def test_text_valid() -> None:
    clean = validate_custom_fields([_def()], {"f": "hello"})
    assert clean.plain == {"f": "hello"}


@pytest.mark.parametrize("value", [1, True, 1.5, None, ["x"], {}])
def test_text_wrong_type(value: object) -> None:
    if value is None:
        return  # covered by the null-handling tests above
    with pytest.raises(CustomFieldValidationError):
        validate_custom_fields([_def()], {"f": value})


def test_text_min_length() -> None:
    with pytest.raises(CustomFieldValidationError):
        validate_custom_fields([_def(rules={"min": 5})], {"f": "ab"})
    assert validate_custom_fields([_def(rules={"min": 2})], {"f": "ab"}).plain == {"f": "ab"}


def test_text_max_length() -> None:
    with pytest.raises(CustomFieldValidationError):
        validate_custom_fields([_def(rules={"max": 2})], {"f": "abc"})


def test_text_over_absolute_cap_is_refused() -> None:
    with pytest.raises(CustomFieldValidationError):
        validate_custom_fields([_def()], {"f": "x" * (MAX_TEXT_LENGTH + 1)})


def test_text_regex_full_match() -> None:
    defn = _def(rules={"regex": r"[A-Z]{3}-\d{4}"})
    assert validate_custom_fields([defn], {"f": "ABC-1234"}).plain == {"f": "ABC-1234"}
    with pytest.raises(CustomFieldValidationError):
        validate_custom_fields([defn], {"f": "xABC-1234x"})
    with pytest.raises(CustomFieldValidationError):
        validate_custom_fields([defn], {"f": "abc-1234"})


def test_text_regex_pattern_over_definition_cap_is_refused_at_value_time_too() -> None:
    defn = _def(rules={"regex": "a" * 201})
    with pytest.raises(CustomFieldValidationError):
        validate_custom_fields([defn], {"f": "a"})


# ---------------------------------------------------------------------------------------- number


def test_number_is_stored_as_a_json_number_from_a_number_or_a_numeric_string() -> None:
    plain = validate_custom_fields([_def(field_type="number")], {"f": 10}).plain
    assert plain == {"f": 10}
    assert type(plain["f"]) is int
    assert validate_custom_fields([_def(field_type="number")], {"f": "42"}).plain == {"f": 42}
    assert validate_custom_fields([_def(field_type="number")], {"f": "10.50"}).plain == {"f": 10.5}


def test_number_decimal_fraction_is_parsed_from_its_text() -> None:
    clean = validate_custom_fields([_def(field_type="number")], {"f": "0.1"})
    assert clean.plain["f"] == 0.1


@pytest.mark.parametrize("value", ["NaN", "Infinity", float("inf")])
def test_number_refuses_non_finite_values(value: object) -> None:
    with pytest.raises(CustomFieldValidationError):
        validate_custom_fields([_def(field_type="number")], {"f": value})


@pytest.mark.parametrize("value", ["not-a-number", True, [1], {}, None])
def test_number_wrong_type(value: object) -> None:
    if value is None:
        return
    with pytest.raises(CustomFieldValidationError):
        validate_custom_fields([_def(field_type="number")], {"f": value})


def test_number_min_max() -> None:
    defn = _def(field_type="number", rules={"min": 1, "max": 10})
    assert validate_custom_fields([defn], {"f": 5}).plain == {"f": 5}
    with pytest.raises(CustomFieldValidationError):
        validate_custom_fields([defn], {"f": 0})
    with pytest.raises(CustomFieldValidationError):
        validate_custom_fields([defn], {"f": 11})


# ------------------------------------------------------------------------------------------ date


def test_date_valid() -> None:
    assert validate_custom_fields([_def(field_type="date")], {"f": "2026-01-15"}).plain == {"f": "2026-01-15"}


@pytest.mark.parametrize("value", ["not-a-date", "2026-13-40", 20260115])
def test_date_invalid(value: object) -> None:
    with pytest.raises(CustomFieldValidationError):
        validate_custom_fields([_def(field_type="date")], {"f": value})


def test_date_min_max() -> None:
    defn = _def(field_type="date", rules={"min": "2026-01-01", "max": "2026-12-31"})
    assert validate_custom_fields([defn], {"f": "2026-06-01"}).plain == {"f": "2026-06-01"}
    with pytest.raises(CustomFieldValidationError):
        validate_custom_fields([defn], {"f": "2025-12-31"})
    with pytest.raises(CustomFieldValidationError):
        validate_custom_fields([defn], {"f": "2027-01-01"})


# --------------------------------------------------------------------------------------- boolean


def test_boolean_valid() -> None:
    assert validate_custom_fields([_def(field_type="boolean")], {"f": True}).plain == {"f": True}
    assert validate_custom_fields([_def(field_type="boolean")], {"f": False}).plain == {"f": False}


@pytest.mark.parametrize("value", ["true", "false", 1, 0, "1", "yes"])
def test_boolean_no_truthy_strings(value: object) -> None:
    with pytest.raises(CustomFieldValidationError):
        validate_custom_fields([_def(field_type="boolean")], {"f": value})


# ---------------------------------------------------------------------------------------- select


def test_select_valid() -> None:
    defn = _def(field_type="select", rules={"options": ["a", "b"]})
    assert validate_custom_fields([defn], {"f": "a"}).plain == {"f": "a"}


def test_select_not_an_option() -> None:
    defn = _def(field_type="select", rules={"options": ["a", "b"]})
    with pytest.raises(CustomFieldValidationError):
        validate_custom_fields([defn], {"f": "c"})


def test_select_wrong_type() -> None:
    defn = _def(field_type="select", rules={"options": ["a"]})
    with pytest.raises(CustomFieldValidationError):
        validate_custom_fields([defn], {"f": ["a"]})


# ---------------------------------------------------------------------------------- multi_select


def test_multi_select_valid() -> None:
    defn = _def(field_type="multi_select", rules={"options": ["a", "b", "c"]})
    assert validate_custom_fields([defn], {"f": ["a", "c"]}).plain == {"f": ["a", "c"]}


def test_multi_select_unknown_option() -> None:
    defn = _def(field_type="multi_select", rules={"options": ["a", "b"]})
    with pytest.raises(CustomFieldValidationError):
        validate_custom_fields([defn], {"f": ["a", "z"]})


def test_multi_select_duplicate_option() -> None:
    defn = _def(field_type="multi_select", rules={"options": ["a", "b"]})
    with pytest.raises(CustomFieldValidationError):
        validate_custom_fields([defn], {"f": ["a", "a"]})


def test_multi_select_min_max_count() -> None:
    defn = _def(field_type="multi_select", rules={"options": ["a", "b", "c"], "min": 1, "max": 2})
    with pytest.raises(CustomFieldValidationError):
        validate_custom_fields([defn], {"f": []})
    with pytest.raises(CustomFieldValidationError):
        validate_custom_fields([defn], {"f": ["a", "b", "c"]})
    assert validate_custom_fields([defn], {"f": ["a", "b"]}).plain == {"f": ["a", "b"]}


# ------------------------------------------------------------------------------------------ json


def test_json_object_and_array_valid() -> None:
    assert validate_custom_fields([_def(field_type="json")], {"f": {"a": 1}}).plain == {"f": {"a": 1}}
    assert validate_custom_fields([_def(field_type="json")], {"f": [1, 2, 3]}).plain == {"f": [1, 2, 3]}


@pytest.mark.parametrize("value", ["text", 1, True])
def test_json_scalar_is_refused(value: object) -> None:
    with pytest.raises(CustomFieldValidationError):
        validate_custom_fields([_def(field_type="json")], {"f": value})


def test_json_over_size_cap_is_refused() -> None:
    big = {"pad": "x" * (MAX_JSON_BYTES + 100)}
    with pytest.raises(CustomFieldValidationError):
        validate_custom_fields([_def(field_type="json")], {"f": big})


# ------------------------------------------------------------------------------------- hypothesis


def _containers(children: st.SearchStrategy[object]) -> st.SearchStrategy[object]:
    return st.lists(children, max_size=3) | st.dictionaries(st.text(max_size=10), children, max_size=3)


_SIMPLE_JSON = st.recursive(
    st.none() | st.booleans() | st.integers(min_value=-1000, max_value=1000) | st.text(max_size=20),
    _containers,
    max_leaves=10,
)


@given(value=_SIMPLE_JSON)
def test_json_valid_output_always_revalidates(value: object) -> None:
    if not isinstance(value, dict | list):
        return
    try:
        clean = validate_custom_fields([_def(field_type="json")], {"f": value})
    except CustomFieldValidationError:
        return
    again = validate_custom_fields([_def(field_type="json")], {"f": clean.plain["f"]})
    assert again.plain == clean.plain


@given(
    value=st.decimals(
        allow_nan=False, allow_infinity=False, places=4, min_value=-1_000_000, max_value=1_000_000
    )
)
def test_number_valid_output_always_revalidates(value: object) -> None:
    clean = validate_custom_fields([_def(field_type="number")], {"f": str(value)})
    again = validate_custom_fields([_def(field_type="number")], {"f": clean.plain["f"]})
    assert again.plain == clean.plain


@given(value=st.text(alphabet=st.characters(min_codepoint=32, max_codepoint=126), max_size=50))
def test_text_valid_output_always_revalidates(value: str) -> None:
    clean = validate_custom_fields([_def()], {"f": value})
    again = validate_custom_fields([_def()], {"f": clean.plain["f"]})
    assert again.plain == clean.plain


# --------------------------------------------------------------------------- encrypted filtering


def test_refuse_encrypted_field_filter_raises_on_a_match() -> None:
    with pytest.raises(ValidationFailedError) as exc:
        refuse_encrypted_field_filter("ssn", encrypted_keys={"ssn", "other"}, where="query.filter.ssn")
    assert exc.value.errors is not None
    assert exc.value.errors[0].field == "query.filter.ssn"
    assert exc.value.code == "validation.invalid_field"


def test_refuse_encrypted_field_filter_passes_a_non_encrypted_key() -> None:
    refuse_encrypted_field_filter("model", encrypted_keys={"ssn"}, where="query.filter.model")


def test_clean_values_defaults_are_independent_between_instances() -> None:
    # A dataclass field(default_factory=dict) must not share state between instances.
    a, b = CleanValues(), CleanValues()
    a.plain["x"] = 1
    assert "x" not in b.plain
