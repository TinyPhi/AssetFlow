# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Domain template model: `config/domains/*.yaml` (§B7.3, §B7.4).

Only the `automations` section is modeled here (M1.5-T2). The other sections (`vocabulary`,
`organization`, `assets.*`, `maintenance.*`) belong to the plans that need them; `extra="allow"`
lets a real template carry them today without this model rejecting the file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from app.engines.automation.conditions import referenced_fields
from app.engines.automation.models import AutomationRule
from app.engines.automation.registry import EventFieldRegistry

__all__ = ["DomainTemplate", "DomainTemplateError", "load_domain_template", "validate_automations"]


class DomainTemplate(BaseModel):
    """One `config/domains/<domain_key>.yaml` file."""

    model_config = ConfigDict(extra="allow")

    domain_key: str
    automations: list[AutomationRule] = []


class DomainTemplateError(Exception):
    """An invalid domain template file; `path` is where the problem is, for the exact-path rule (§B7.4)."""

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}")


def load_domain_template(file: Path) -> DomainTemplate:
    """Parse and validate `file`; raises `DomainTemplateError` naming the exact path on failure."""
    try:
        data: Any = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise DomainTemplateError(str(file), str(exc)) from exc
    try:
        return DomainTemplate.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(part) for part in first["loc"])
        raise DomainTemplateError(f"{file}:{loc}", first["msg"]) from exc


def validate_automations(
    template: DomainTemplate,
    *,
    known_channels: set[str],
    registry: EventFieldRegistry,
    templates_dir: Path,
) -> list[str]:
    """Every cross-reference problem in `template.automations` (empty when it is valid), §B7.4.

    Each problem names the exact path (`automations[<i>].<field>`), as the master plan's own
    example does (`maintenance.priority_matrix.map[1][2]: unknown priority "p5"`).
    """
    problems: list[str] = []
    for index, rule in enumerate(template.automations):
        path = f"automations[{index}]"
        spec = registry.get(rule.when)
        if spec is None:
            problems.append(f"{path}.when: event {rule.when!r} is not registered")
            continue
        for field_name in sorted(referenced_fields(rule.if_)):
            if field_name not in spec.fields:
                problems.append(f"{path}.if: field {field_name!r} is not registered for event {rule.when!r}")
        for channel_key in rule.then.channels:
            if channel_key not in known_channels:
                problems.append(f"{path}.then.channels: channel {channel_key!r} is not registered")
        if not _template_exists(templates_dir, rule.then.template):
            problems.append(
                f"{path}.then.template: template {rule.then.template!r} not found under {templates_dir}"
            )
        for recipient_index, ref in enumerate(rule.then.recipients):
            recipient_path = f"{path}.then.recipients[{recipient_index}]"
            if ref.kind == "team" and ref.team_field not in spec.fields:
                problems.append(
                    f"{recipient_path}: field {ref.team_field!r} is not registered for event {rule.when!r}"
                )
            if ref.kind == "role" and ref.scope != "organization" and ref.scope_field not in spec.fields:
                problems.append(
                    f"{recipient_path}: field {ref.scope_field!r} is not registered for event {rule.when!r}"
                )
    return problems


def _template_exists(templates_dir: Path, template_key: str) -> bool:
    return any((templates_dir / f"{template_key}{suffix}").exists() for suffix in (".html", ".txt"))
