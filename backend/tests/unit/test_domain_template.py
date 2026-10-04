# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Unit tests for the domain template model and its automation cross-checks (§B7.3, §B7.4)."""

from __future__ import annotations

from pathlib import Path

from app.core.domain_template import DomainTemplateError, load_domain_template, validate_automations
from app.engines.automation.registry import EventFieldRegistry, default_registry

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "domains" / "test-neutral.yaml"


def _templates_dir_with(tmp_path: Path, *names: str) -> Path:
    templates = tmp_path / "templates" / "en"
    templates.mkdir(parents=True)
    for name in names:
        (templates / f"{name}.html").write_text("<p>test</p>", encoding="utf-8")
    return templates


def test_the_fixture_template_loads() -> None:
    template = load_domain_template(FIXTURE)
    assert template.domain_key == "test-neutral"
    assert len(template.automations) == 1
    assert template.automations[0].when == "team_member.added"


def test_the_fixture_template_passes_its_cross_checks_when_its_template_exists(tmp_path: Path) -> None:
    templates_dir = _templates_dir_with(tmp_path, "team-member-added")
    template = load_domain_template(FIXTURE)
    problems = validate_automations(
        template,
        known_channels={"inapp", "email", "webhook"},
        registry=default_registry(),
        templates_dir=templates_dir,
    )
    assert problems == []


def test_a_missing_template_file_is_a_cross_check_problem(tmp_path: Path) -> None:
    templates_dir = _templates_dir_with(tmp_path)  # no files at all
    template = load_domain_template(FIXTURE)
    problems = validate_automations(
        template, known_channels={"inapp"}, registry=default_registry(), templates_dir=templates_dir
    )
    assert any("team-member-added" in p and "not found" in p for p in problems)


def test_an_unregistered_channel_is_a_cross_check_problem(tmp_path: Path) -> None:
    templates_dir = _templates_dir_with(tmp_path, "team-member-added")
    template = load_domain_template(FIXTURE)
    problems = validate_automations(
        template, known_channels=set(), registry=default_registry(), templates_dir=templates_dir
    )
    assert any("inapp" in p and "is not registered" in p for p in problems)


def test_an_unregistered_event_is_a_cross_check_problem(tmp_path: Path) -> None:
    registry = EventFieldRegistry()  # empty: nothing registered
    templates_dir = _templates_dir_with(tmp_path, "team-member-added")
    template = load_domain_template(FIXTURE)
    problems = validate_automations(
        template, known_channels={"inapp"}, registry=registry, templates_dir=templates_dir
    )
    assert any("team_member.added" in p and "not registered" in p for p in problems)


def test_malformed_yaml_raises_naming_its_own_file() -> None:
    bad = Path(__file__).parent / "_malformed.yaml.tmp"
    bad.write_text("domain_key: [unterminated\n", encoding="utf-8")
    try:
        load_domain_template(bad)
        raise AssertionError("expected a DomainTemplateError")
    except DomainTemplateError as exc:
        assert str(bad) in exc.path
    finally:
        bad.unlink()


def test_a_rule_missing_a_required_field_raises_with_the_exact_path() -> None:
    bad = Path(__file__).parent / "_missing_field.yaml.tmp"
    bad.write_text(
        "domain_key: x\n"
        "automations:\n"
        "  - when: team_member.added\n"
        "    then:\n"
        "      channels: [inapp]\n"
        "      template: t\n",
        encoding="utf-8",
    )
    try:
        load_domain_template(bad)
        raise AssertionError("expected a DomainTemplateError")
    except DomainTemplateError as exc:
        assert "recipients" in exc.path
    finally:
        bad.unlink()
