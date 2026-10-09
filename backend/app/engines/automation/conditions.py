# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Evaluate a structured condition against an event's data (§B7.3, §B7.4).

A pure function: no I/O, no clock, no randomness. Unknown fields are rejected at config load time
(the registry cross-check), never here - by the time a condition reaches ``evaluate``, every field
it names is already known to exist for the event type.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.engines.automation.models import AllCondition, AnyCondition, Condition, FieldCondition

__all__ = ["evaluate", "referenced_fields"]

_COMPARISONS: dict[str, Callable[[Any, Any], bool]] = {
    "equals": lambda value, target: bool(value == target),
    "not_equals": lambda value, target: bool(value != target),
    "in": lambda value, target: value in target,
    "not_in": lambda value, target: value not in target,
    "lt": lambda value, target: bool(value < target),
    "lte": lambda value, target: bool(value <= target),
    "gt": lambda value, target: bool(value > target),
    "gte": lambda value, target: bool(value >= target),
}


def evaluate(condition: Condition | None, data: dict[str, Any]) -> bool:
    """Return whether `condition` holds for `data`; `None` always holds."""
    if condition is None:
        return True
    if isinstance(condition, AllCondition):
        return all(evaluate(c, data) for c in condition.all)
    if isinstance(condition, AnyCondition):
        return any(evaluate(c, data) for c in condition.any)
    return _evaluate_field(condition, data)


def _evaluate_field(condition: FieldCondition, data: dict[str, Any]) -> bool:
    if condition.operator == "exists":
        present = condition.field in data and data[condition.field] is not None
        return present == bool(condition.value)
    if condition.field not in data or data[condition.field] is None:
        return False
    return _COMPARISONS[condition.operator](data[condition.field], condition.value)


def referenced_fields(condition: Condition | None) -> set[str]:
    """Every field name `condition` reads, recursively through `all`/`any` (for the registry cross-check)."""
    if condition is None:
        return set()
    if isinstance(condition, AllCondition):
        return {f for c in condition.all for f in referenced_fields(c)}
    if isinstance(condition, AnyCondition):
        return {f for c in condition.any for f in referenced_fields(c)}
    return {condition.field}
