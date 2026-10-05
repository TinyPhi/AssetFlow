# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The `assets` section of a domain template: shape, cross-references and exact error paths (§B7.4)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.core.permissions import DEFAULT_PERMISSIONS
from app.modules.assets.config import AssetsConfig, parse_assets_section, validate_assets_section
from app.modules.domain_template_check import domain_template_problems

REPO = Path(__file__).resolve().parents[3]
DOMAINS = REPO / "config" / "domains"
PLATFORM_FILE = REPO / "config" / "assetflow.yaml"


def _valid() -> dict[str, Any]:
    return {
        "tag": {"prefix": "AST", "separator": "-", "digits": 5},
        "initial": "in_stock",
        "statuses": [
            {"key": "in_stock", "label": "In stock", "category": "available"},
            {"key": "assigned", "label": "Assigned", "category": "in_use"},
            {"key": "retired", "label": "Retired", "category": "ended"},
        ],
        "transitions": [
            {"from": "in_stock", "to": "assigned", "permission": "asset.assign"},
            {
                "from": "in_stock",
                "to": "retired",
                "permission": "asset.retire",
                "requires_reason": True,
                "conditions": [{"field": "holder", "operator": "exists", "value": False}],
            },
        ],
        "categories": [
            {
                "code": "laptop",
                "label": "Laptop",
                "default_criticality": "medium",
                "custom_fields": [
                    {"key": "ram_gb", "label": "RAM (GB)", "type": "number", "min": 1, "max": 512},
                    {"key": "secret_note", "label": "Note", "type": "text", "is_encrypted": True},
                ],
            }
        ],
        "public_scan_fields": ["tag", "name"],
    }


def _problems(section: Any) -> list[str]:
    return validate_assets_section(section, known_permissions=DEFAULT_PERMISSIONS)


def _edit(mutate: Any) -> dict[str, Any]:
    section = copy.deepcopy(_valid())
    mutate(section)
    return section


def test_the_baseline_section_is_valid_and_defaults_apply() -> None:
    assert _problems(_valid()) == []
    config = parse_assets_section(_valid())
    assert config.owner_follows_holder is True
    assert config.cascade_on_member_move == "ask"
    assert config.criticality == ["low", "medium", "high", "critical"]
    assert config.public_report is False
    status = config.status("retired")
    assert status is not None and status.final and not status.assignable
    assigned = config.status("assigned")
    assert assigned is not None and not assigned.final and assigned.assignable


def test_a_non_mapping_section_is_refused() -> None:
    assert _problems(["x"]) == ["assets: must be a mapping"]


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda s: s["statuses"][2].update(category="gone"),
            'assets.statuses[2].category: unknown category "gone"',
        ),
        (lambda s: s.update(initial="nope"), 'assets.initial: unknown status "nope"'),
        (
            lambda s: s.update(initial="retired"),
            'assets.initial: status "retired" is final and cannot be the initial status',
        ),
        (
            lambda s: s["statuses"].append(dict(s["statuses"][0])),
            "assets.statuses[0].key: duplicate status 'in_stock'",
        ),
        (
            lambda s: s["transitions"][0].update(to="ghost"),
            'assets.transitions[0].to: unknown status "ghost"',
        ),
        (
            lambda s: s["transitions"][0].update(**{"from": "ghost"}),
            'assets.transitions[0].from: unknown status "ghost"',
        ),
        (
            lambda s: s["transitions"][0].update(to="in_stock"),
            "assets.transitions[0].to: a transition must change the status",
        ),
        (
            lambda s: s["transitions"].append(dict(s["transitions"][0])),
            'assets.transitions[2]: duplicate transition "in_stock" -> "assigned"',
        ),
        (
            lambda s: s["transitions"][0].update(permission="asset.fly"),
            'assets.transitions[0].permission: unknown permission "asset.fly"',
        ),
        (
            lambda s: s["transitions"][1]["conditions"][0].update(field="mood"),
            'assets.transitions[1].conditions[0].field: unknown asset field "mood"',
        ),
        (
            lambda s: s["transitions"][1]["conditions"][0].update(operator="matches"),
            "assets.transitions[1].conditions[0]",
        ),
        (
            lambda s: s["categories"][0].update(parent_code="gone"),
            'assets.categories[0].parent_code: unknown category "gone"',
        ),
        (
            lambda s: s["categories"][0].update(default_criticality="extreme"),
            'assets.categories[0].default_criticality: unknown criticality "extreme"',
        ),
        (
            lambda s: s["categories"].append(dict(s["categories"][0])),
            "assets.categories[0].code: duplicate category 'laptop'",
        ),
        (
            lambda s: s["categories"][0]["custom_fields"].append(
                dict(s["categories"][0]["custom_fields"][0])
            ),
            "assets.categories[0].custom_fields[2].key: duplicate field 'ram_gb'",
        ),
        (
            lambda s: s["tag"].update(digits=2),
            "assets.tag.digits: Input should be greater than or equal to 3",
        ),
        (lambda s: s["tag"].update(prefix="ast-"), "assets.tag.prefix: prefix must be"),
        (lambda s: s["tag"].update(separator="##"), "assets.tag.separator: separator must be"),
        (lambda s: s.update(bogus=1), "assets.bogus: Extra inputs are not permitted"),
        (
            lambda s: s.update(cascade_on_member_move="sometimes"),
            "assets.cascade_on_member_move: Input should be",
        ),
        (lambda s: s.update(statuses=[]), "assets.statuses: List should have at least 1 item"),
    ],
)
def test_each_rule_reports_its_exact_path(mutate: Any, expected: str) -> None:
    problems = _problems(_edit(mutate))
    assert any(problem.startswith(expected) for problem in problems), problems


def test_a_category_cycle_is_refused() -> None:
    def mutate(section: dict[str, Any]) -> None:
        section["categories"] = [
            {"code": "a", "label": "A", "parent_code": "b"},
            {"code": "b", "label": "B", "parent_code": "a"},
        ]

    problems = _problems(_edit(mutate))
    assert "assets.categories[0].parent_code: category tree has a cycle" in problems
    assert "assets.categories[1].parent_code: category tree has a cycle" in problems


def test_a_category_that_is_its_own_parent_is_a_cycle() -> None:
    problems = _problems(_edit(lambda s: s["categories"][0].update(parent_code="laptop")))
    assert "assets.categories[0].parent_code: category tree has a cycle" in problems


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ({"key": "k", "label": "K", "type": "select"}, "a select field needs at least one option"),
        (
            {"key": "k", "label": "K", "type": "multi_select", "options": []},
            "a multi_select field needs at least one option",
        ),
        ({"key": "k", "label": "K", "type": "select", "options": ["a", "a"]}, "options must be unique"),
        ({"key": "k", "label": "K", "type": "text", "options": ["a"]}, "options are only allowed on select"),
        ({"key": "k", "label": "K", "type": "number", "min": 5, "max": 1}, "min 5 is greater than max 1"),
        ({"key": "k", "label": "K", "type": "text", "regex": "("}, "regex does not compile"),
        (
            {"key": "k", "label": "K", "type": "number", "regex": "^a$"},
            "regex is only allowed on text fields",
        ),
        (
            {"key": "k", "label": "K", "type": "text", "is_unique": True, "is_encrypted": True},
            "an encrypted field cannot be unique",
        ),
        ({"key": "K", "label": "K", "type": "text"}, "must be lowercase letters"),
        ({"key": "k", "label": "K", "type": "color"}, "Input should be"),
    ],
)
def test_custom_field_rules(field: dict[str, Any], expected: str) -> None:
    section = _edit(lambda s: s["categories"][0]["custom_fields"].append(field))
    problems = _problems(section)
    prefix = "assets.categories[0].custom_fields[2]"
    assert any(p.startswith(prefix) and expected in p for p in problems), problems


@pytest.mark.parametrize("kind", ["text", "number", "date", "boolean", "json"])
def test_every_plain_custom_field_type_is_accepted(kind: str) -> None:
    section = _edit(
        lambda s: s["categories"][0]["custom_fields"].append({"key": "k", "label": "K", "type": kind})
    )
    assert _problems(section) == []


@pytest.mark.parametrize("kind", ["select", "multi_select"])
def test_select_custom_field_types_are_accepted_with_options(kind: str) -> None:
    field = {"key": "k", "label": "K", "type": kind, "options": ["a", "b"]}
    assert _problems(_edit(lambda s: s["categories"][0]["custom_fields"].append(field))) == []


@pytest.mark.parametrize(
    ("hours", "expected"),
    [
        (
            {"remind_after_hours": 0},
            "assets.acknowledgement.remind_after_hours: Input should be greater than 0",
        ),
        (
            {"escalate_after_hours": -1},
            "assets.acknowledgement.escalate_after_hours: Input should be greater than 0",
        ),
        (
            {"auto_close_after_days": 0},
            "assets.acknowledgement.auto_close_after_days: Input should be greater than 0",
        ),
        (
            {"remind_after_hours": 48, "escalate_after_hours": 24},
            "assets.acknowledgement: escalate_after_hours must be greater",
        ),
    ],
)
def test_acknowledgement_timings_must_be_sensible(hours: dict[str, int], expected: str) -> None:
    problems = _problems(_edit(lambda s: s.update(acknowledgement={"required": True, **hours})))
    assert any(p.startswith(expected) for p in problems), problems


def test_public_scan_fields_refuse_personal_unknown_and_encrypted_fields() -> None:
    def mutate(section: dict[str, Any]) -> None:
        section["public_scan_fields"] = [
            "tag",
            "holder",
            "serial_number",
            "custom.secret_note",
            "custom.ghost",
            "custom.ram_gb",
        ]

    problems = _problems(_edit(mutate))
    assert 'assets.public_scan_fields[1]: field "holder" is personal data and cannot be public' in problems
    assert 'assets.public_scan_fields[2]: field "serial_number" is not an allowed public field' in problems
    assert (
        'assets.public_scan_fields[3]: field "custom.secret_note" is encrypted and cannot be public'
        in problems
    )
    assert 'assets.public_scan_fields[4]: unknown custom field "custom.ghost"' in problems
    assert len(problems) == 4  # custom.ram_gb is a plain custom field and is allowed


def test_a_yaml_boolean_off_is_read_as_the_off_setting() -> None:
    config = parse_assets_section(_edit(lambda s: s.update(cascade_on_member_move=False)))
    assert config.cascade_on_member_move == "off"


@pytest.mark.parametrize("name", ["it-assets", "facilities"])
def test_both_shipped_templates_load_and_validate(name: str) -> None:
    data = yaml.safe_load((DOMAINS / f"{name}.yaml").read_text(encoding="utf-8"))
    assert data["domain_key"] == name
    assert _problems(data["assets"]) == []
    config = parse_assets_section(data["assets"])
    assert isinstance(config, AssetsConfig)
    assert config.statuses and config.categories and config.transitions


def test_the_two_templates_really_differ() -> None:
    loaded = {
        name: parse_assets_section(
            yaml.safe_load((DOMAINS / f"{name}.yaml").read_text(encoding="utf-8"))["assets"]
        )
        for name in ("it-assets", "facilities")
    }
    it, fac = loaded["it-assets"], loaded["facilities"]
    assert it.tag.prefix != fac.tag.prefix
    assert {c.code for c in it.categories}.isdisjoint({c.code for c in fac.categories})
    assert {s.label for s in it.statuses} != {s.label for s in fac.statuses}
    assert it.criticality != fac.criticality


def test_the_it_assets_template_matches_the_master_plan_examples() -> None:
    config = parse_assets_section(
        yaml.safe_load((DOMAINS / "it-assets.yaml").read_text(encoding="utf-8"))["assets"]
    )
    assert (config.tag.prefix, config.tag.separator, config.tag.digits) == ("AST", "-", 5)
    assert {s.key: s.category for s in config.statuses} == {
        "in_stock": "available",
        "assigned": "in_use",
        "in_service": "in_use",
        "under_maintenance": "unavailable",
        "in_repair": "unavailable",
        "retired": "ended",
        "lost": "ended",
        "disposed": "ended",
    }
    maintenance = config.status("under_maintenance")
    assert maintenance is not None and maintenance.set_only_by == "maintenance"
    laptop = config.category("laptop")
    assert laptop is not None and laptop.default_criticality == "medium"
    assert {f.key: f.type for f in laptop.custom_fields}["ram_gb"] == "number"
    assert config.public_scan_fields == ["tag", "name", "category", "status", "owner_org_unit"]
    assert config.public_report is True
    assert (config.acknowledgement.required, config.acknowledgement.remind_after_hours) == (True, 24)
    assert config.acknowledgement.escalate_after_hours == 72


def test_shipped_domain_files_pass_the_boot_check() -> None:
    assert domain_template_problems(str(PLATFORM_FILE)) == []


def test_an_invalid_asset_section_is_reported_by_the_boot_check_with_file_and_path(tmp_path: Path) -> None:
    domains = tmp_path / "domains"
    domains.mkdir()
    (tmp_path / "assetflow.yaml").write_text("", encoding="utf-8")
    section = _edit(lambda s: s["statuses"][2].update(category="gone"))
    (domains / "broken.yaml").write_text(
        yaml.safe_dump({"domain_key": "broken", "assets": section}), encoding="utf-8"
    )
    problems = domain_template_problems(str(tmp_path / "assetflow.yaml"))
    assert problems == ['broken.yaml: assets.statuses[2].category: unknown category "gone"']
