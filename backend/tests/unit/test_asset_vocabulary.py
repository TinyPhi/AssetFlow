# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The asset vocabulary served to the screens (§B8.1, P8-11): labels and levels come from the template."""

from __future__ import annotations

from pathlib import Path

import yaml

from app.modules.assets.config import parse_assets_section
from app.modules.assets.service import vocabulary_of

DOMAINS = Path(__file__).resolve().parents[3] / "config" / "domains"


def test_vocabulary_lists_statuses_with_labels_and_the_criticality_levels() -> None:
    raw = yaml.safe_load((DOMAINS / "it-assets.yaml").read_text(encoding="utf-8"))["assets"]
    template = parse_assets_section(raw)
    vocabulary = vocabulary_of(template)
    assert [s.key for s in vocabulary.statuses] == [s.key for s in template.statuses]
    assert all(s.label and s.category for s in vocabulary.statuses)
    assert vocabulary.criticality == list(template.criticality)


def test_vocabulary_is_empty_without_a_template() -> None:
    vocabulary = vocabulary_of(None)
    assert vocabulary.statuses == []
    assert vocabulary.criticality == []
