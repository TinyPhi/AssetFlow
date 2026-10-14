# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Asset lifecycle rules over both shipped templates and each condition operator (§B8.1, P8-08)."""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.modules.assets.config import AssetsConfig, parse_assets_section
from app.modules.assets.errors import AssetInvalidTransitionError
from app.modules.assets.lifecycle import (
    AssetSnapshot,
    allowed_transitions,
    check_transition,
    find_transition,
)

DOMAINS = Path(__file__).resolve().parents[3] / "config" / "domains"
TEMPLATES = ("it-assets", "facilities")


def _load(key: str) -> AssetsConfig:
    raw = yaml.safe_load((DOMAINS / f"{key}.yaml").read_text(encoding="utf-8"))
    return parse_assets_section(raw["assets"])


def _pairs(key: str) -> list[tuple[str, str, str]]:
    template = _load(key)
    return [(key, t.from_, t.to) for t in template.transitions]


def _undeclared(key: str) -> list[tuple[str, str, str]]:
    template = _load(key)
    declared = {(t.from_, t.to) for t in template.transitions}
    keys = [s.key for s in template.statuses if s.set_only_by is None]
    return [(key, a, b) for a, b in itertools.product(keys, keys) if (a, b) not in declared]


ALL_DECLARED = [pair for key in TEMPLATES for pair in _pairs(key)]
ALL_UNDECLARED = [pair for key in TEMPLATES for pair in _undeclared(key)]


def _reason_code(template: AssetsConfig, snapshot: AssetSnapshot, to: str, reason: str | None) -> str:
    with pytest.raises(AssetInvalidTransitionError) as caught:
        check_transition(template, snapshot, to, reason=reason)
    return caught.value.reason_code


@pytest.mark.parametrize(("key", "from_status", "to_status"), ALL_DECLARED)
def test_every_declared_transition_is_allowed(key: str, from_status: str, to_status: str) -> None:
    template = _load(key)
    transition = check_transition(template, AssetSnapshot(status=from_status), to_status, reason="because")
    assert (transition.from_, transition.to) == (from_status, to_status)
    assert transition in allowed_transitions(template, from_status)


@pytest.mark.parametrize(("key", "from_status", "to_status"), ALL_UNDECLARED)
def test_every_undeclared_pair_is_refused(key: str, from_status: str, to_status: str) -> None:
    template = _load(key)
    with pytest.raises(AssetInvalidTransitionError) as caught:
        check_transition(template, AssetSnapshot(status=from_status), to_status, reason="because")
    assert caught.value.reason_code == "not_allowed"
    assert (caught.value.from_status, caught.value.to_status) == (from_status, to_status)
    assert from_status in caught.value.detail
    assert to_status in caught.value.detail


@pytest.mark.parametrize(("key", "from_status", "to_status"), ALL_DECLARED)
def test_reason_required_only_where_declared(key: str, from_status: str, to_status: str) -> None:
    template = _load(key)
    transition = find_transition(template, from_status, to_status)
    assert transition is not None
    snapshot = AssetSnapshot(status=from_status)
    if transition.requires_reason:
        assert _reason_code(template, snapshot, to_status, None) == "reason_required"
        assert _reason_code(template, snapshot, to_status, "   ") == "reason_required"
    else:
        check_transition(template, snapshot, to_status, reason=None)


@pytest.mark.parametrize(("key", "from_status", "to_status"), ALL_DECLARED)
def test_ended_target_refused_while_a_holder_is_set(key: str, from_status: str, to_status: str) -> None:
    template = _load(key)
    target = template.status(to_status)
    assert target is not None
    snapshot = AssetSnapshot(status=from_status, holder_type="member", holder_id="m-1")
    if target.category == "ended":
        code = _reason_code(template, snapshot, to_status, "because")
        assert code.startswith("condition_failed:")
    else:
        check_transition(template, snapshot, to_status, reason="because")


@pytest.mark.parametrize("key", TEMPLATES)
def test_reserved_status_is_refused_for_api_callers(key: str) -> None:
    template = _load(key)
    reserved = [s for s in template.statuses if s.set_only_by is not None]
    assert reserved, "each shipped template reserves a status for the maintenance module"
    for status in reserved:
        for source in template.statuses:
            if source.key == status.key:
                continue
            code = _reason_code(template, AssetSnapshot(status=source.key), status.key, "because")
            assert code == f"reserved_for_module:{status.set_only_by}"


@pytest.mark.parametrize("key", TEMPLATES)
def test_unknown_statuses_are_refused(key: str) -> None:
    template = _load(key)
    first = template.statuses[0].key
    assert _reason_code(template, AssetSnapshot(status=first), "nonsense", "x") == "unknown_status"
    assert _reason_code(template, AssetSnapshot(status="nonsense"), first, "x") == "unknown_status"


@pytest.mark.parametrize("key", TEMPLATES)
def test_final_statuses_have_no_way_out(key: str) -> None:
    template = _load(key)
    for status in template.statuses:
        if status.final:
            assert allowed_transitions(template, status.key) == []


def _template_with(condition: dict[str, Any]) -> AssetsConfig:
    return parse_assets_section(
        {
            "tag": {"prefix": "AST", "digits": 5},
            "initial": "a",
            "statuses": [
                {"key": "a", "label": "A", "category": "available"},
                {"key": "b", "label": "B", "category": "in_use"},
            ],
            "transitions": [{"from": "a", "to": "b", "conditions": [condition]}],
        }
    )


def _cond(field: str, operator: str, value: object = None) -> dict[str, Any]:
    return {"field": field, "operator": operator, "value": value}


OPERATOR_CASES: list[tuple[dict[str, Any], AssetSnapshot, bool]] = [
    (_cond("criticality", "equals", "high"), AssetSnapshot("a", criticality="high"), True),
    (_cond("criticality", "equals", "high"), AssetSnapshot("a", criticality="low"), False),
    (_cond("criticality", "not_equals", "high"), AssetSnapshot("a", criticality="low"), True),
    (_cond("criticality", "not_equals", "high"), AssetSnapshot("a", criticality="high"), False),
    (_cond("criticality", "in", ["high", "critical"]), AssetSnapshot("a", criticality="critical"), True),
    (_cond("criticality", "in", ["high", "critical"]), AssetSnapshot("a", criticality="low"), False),
    (_cond("criticality", "not_in", ["high"]), AssetSnapshot("a", criticality="low"), True),
    (_cond("criticality", "not_in", ["high"]), AssetSnapshot("a", criticality="high"), False),
    (_cond("custom.ram_gb", "lt", 8), AssetSnapshot("a", custom_fields={"ram_gb": 4}), True),
    (_cond("custom.ram_gb", "lt", 8), AssetSnapshot("a", custom_fields={"ram_gb": 8}), False),
    (_cond("custom.ram_gb", "lte", 8), AssetSnapshot("a", custom_fields={"ram_gb": 8}), True),
    (_cond("custom.ram_gb", "lte", 8), AssetSnapshot("a", custom_fields={"ram_gb": 9}), False),
    (_cond("custom.ram_gb", "gt", 8), AssetSnapshot("a", custom_fields={"ram_gb": 9}), True),
    (_cond("custom.ram_gb", "gt", 8), AssetSnapshot("a", custom_fields={"ram_gb": 8}), False),
    (_cond("custom.ram_gb", "gte", 8), AssetSnapshot("a", custom_fields={"ram_gb": 8}), True),
    (_cond("custom.ram_gb", "gte", 8), AssetSnapshot("a", custom_fields={"ram_gb": 7}), False),
    (_cond("custom.ram_gb", "exists", True), AssetSnapshot("a", custom_fields={"ram_gb": 7}), True),
    (_cond("custom.ram_gb", "exists", True), AssetSnapshot("a"), False),
    (_cond("holder.is_set", "equals", False), AssetSnapshot("a"), True),
    (_cond("holder.is_set", "equals", False), AssetSnapshot("a", holder_type="team", holder_id="t"), False),
    (_cond("holder.type", "equals", "member"), AssetSnapshot("a", holder_type="member", holder_id="m"), True),
    (_cond("holder.type", "equals", "member"), AssetSnapshot("a", holder_type="team", holder_id="t"), False),
    (_cond("status.category", "equals", "available"), AssetSnapshot("a"), True),
    (_cond("status.category", "equals", "in_use"), AssetSnapshot("a"), False),
    (_cond("category.code", "equals", "laptop"), AssetSnapshot("a", category_code="laptop"), True),
    (_cond("category.code", "in", ["server"]), AssetSnapshot("a", category_code="laptop"), False),
]


@pytest.mark.parametrize(("condition", "snapshot", "passes"), OPERATOR_CASES)
def test_each_condition_operator(condition: dict[str, Any], snapshot: AssetSnapshot, passes: bool) -> None:
    template = parse_assets_section(
        {
            **_template_with(condition).model_dump(by_alias=True, mode="json"),
            "categories": [
                {
                    "code": "laptop",
                    "label": "Laptop",
                    "custom_fields": [{"key": "ram_gb", "label": "RAM", "type": "number"}],
                }
            ],
        }
    )
    if passes:
        check_transition(template, snapshot, "b", reason=None)
    else:
        field = condition["field"]
        assert _reason_code(template, snapshot, "b", None) == f"condition_failed:{field}"


def test_all_and_any_combinators() -> None:
    both = _cond("criticality", "equals", "high")
    holder_free = _cond("holder.is_set", "equals", False)
    all_template = _template_with({"all": [both, holder_free]})
    any_template = _template_with({"any": [both, holder_free]})

    high_with_holder = AssetSnapshot("a", criticality="high", holder_type="member", holder_id="m")
    check_transition(any_template, high_with_holder, "b", reason=None)
    assert _reason_code(all_template, high_with_holder, "b", None).startswith("condition_failed:")
    check_transition(all_template, AssetSnapshot("a", criticality="high"), "b", reason=None)
    low_with_holder = AssetSnapshot("a", criticality="low", holder_type="member", holder_id="m")
    assert _reason_code(any_template, low_with_holder, "b", None).startswith("condition_failed:")


def test_refusal_message_names_statuses_and_remedy() -> None:
    template = _load("it-assets")
    with pytest.raises(AssetInvalidTransitionError) as caught:
        check_transition(
            template, AssetSnapshot("in_stock", holder_type="member", holder_id="m"), "retired", reason="x"
        )
    detail = caught.value.detail
    assert '"in_stock"' in detail
    assert '"retired"' in detail
    assert "holder" in detail
    assert caught.value.status_code == 409
    assert caught.value.code == "asset.invalid_transition"
