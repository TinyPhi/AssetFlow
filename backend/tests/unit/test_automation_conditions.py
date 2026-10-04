# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Unit tests for the automation condition evaluator (§B7.3, §B7.4, M1.5-T2)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.engines.automation.conditions import evaluate, referenced_fields
from app.engines.automation.models import AllCondition, AnyCondition, FieldCondition


@pytest.mark.parametrize(
    ("operator", "value", "data_value", "expected"),
    [
        ("equals", "high", "high", True),
        ("equals", "high", "low", False),
        ("not_equals", "high", "low", True),
        ("not_equals", "high", "high", False),
        ("in", ["high", "critical"], "high", True),
        ("in", ["high", "critical"], "low", False),
        ("not_in", ["high", "critical"], "low", True),
        ("not_in", ["high", "critical"], "high", False),
        ("lt", 30, 7, True),
        ("lt", 30, 30, False),
        ("lte", 30, 30, True),
        ("gt", 7, 30, True),
        ("gt", 7, 7, False),
        ("gte", 7, 7, True),
    ],
)
def test_every_comparison_operator(operator: str, value: object, data_value: object, expected: bool) -> None:
    condition = FieldCondition(field="severity", operator=operator, value=value)
    assert evaluate(condition, {"severity": data_value}) is expected


def test_exists_true_when_present_and_non_null() -> None:
    condition = FieldCondition(field="reason", operator="exists", value=True)
    assert evaluate(condition, {"reason": "late"}) is True
    assert evaluate(condition, {"reason": None}) is False
    assert evaluate(condition, {}) is False


def test_exists_false_means_the_field_must_be_absent() -> None:
    condition = FieldCondition(field="reason", operator="exists", value=False)
    assert evaluate(condition, {}) is True
    assert evaluate(condition, {"reason": "late"}) is False


def test_a_missing_field_never_matches_a_non_exists_operator() -> None:
    condition = FieldCondition(field="severity", operator="equals", value="high")
    assert evaluate(condition, {}) is False
    assert evaluate(condition, {"severity": None}) is False


def test_none_condition_always_holds() -> None:
    assert evaluate(None, {}) is True


def test_all_requires_every_nested_condition() -> None:
    condition = AllCondition(
        all=[
            FieldCondition(field="a", operator="equals", value=1),
            FieldCondition(field="b", operator="equals", value=2),
        ]
    )
    assert evaluate(condition, {"a": 1, "b": 2}) is True
    assert evaluate(condition, {"a": 1, "b": 3}) is False


def test_any_requires_at_least_one_nested_condition() -> None:
    condition = AnyCondition(
        any=[
            FieldCondition(field="a", operator="equals", value=1),
            FieldCondition(field="b", operator="equals", value=2),
        ]
    )
    assert evaluate(condition, {"a": 0, "b": 2}) is True
    assert evaluate(condition, {"a": 0, "b": 0}) is False


def test_all_and_any_nest() -> None:
    condition = AllCondition(
        all=[
            FieldCondition(field="a", operator="equals", value=1),
            AnyCondition(
                any=[
                    FieldCondition(field="b", operator="equals", value=2),
                    FieldCondition(field="c", operator="equals", value=3),
                ]
            ),
        ]
    )
    assert evaluate(condition, {"a": 1, "b": 0, "c": 3}) is True
    assert evaluate(condition, {"a": 1, "b": 0, "c": 0}) is False


def test_an_unknown_operator_is_rejected_at_load_time() -> None:
    with pytest.raises(ValidationError):
        FieldCondition.model_validate({"field": "severity", "operator": "matches", "value": "x"})


def test_referenced_fields_collects_through_all_and_any() -> None:
    condition = AllCondition(
        all=[
            FieldCondition(field="a", operator="equals", value=1),
            AnyCondition(
                any=[
                    FieldCondition(field="b", operator="exists", value=True),
                    FieldCondition(field="a", operator="not_equals", value=2),
                ]
            ),
        ]
    )
    assert referenced_fields(condition) == {"a", "b"}


def test_referenced_fields_of_none_is_empty() -> None:
    assert referenced_fields(None) == set()
