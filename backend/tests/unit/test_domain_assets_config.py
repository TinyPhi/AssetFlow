# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The `assets` section of a domain template: shape, cross-references and exact error paths (§B7.4)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from app.core.permissions import DEFAULT_PERMISSIONS
from app.modules.assets.config import parse_assets_section, validate_assets_section

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
