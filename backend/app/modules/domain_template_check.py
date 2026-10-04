# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Static check of every `config/domains/*.yaml` (§B7.3, §B7.4), run by `python -m app.core.config validate`.

`app.core.config` sits below the engines and modules, so it cannot import them; it loads this
module by name instead (`importlib`), the way a plugin is loaded, so the layering stays one-way.
"""

from __future__ import annotations

from pathlib import Path

from app.engines.automation.domain_template import (
    DomainTemplateError,
    load_domain_template,
    validate_automations,
)
from app.modules.event_registry import default_event_registry

__all__ = ["domain_template_problems"]

#: Channels built into AssetFlow (§B6.3); a third-party channel package extends this at runtime,
#: out of scope for this static check.
BUILTIN_CHANNELS = frozenset({"inapp", "email", "webhook"})


def domain_template_problems(platform_config_file: str) -> list[str]:
    """One problem string per cross-reference failure, each naming its exact path; empty when valid.

    Validates every `config/domains/*.yaml` next to `platform_config_file`; nothing to check yet
    when there is no such directory.
    """
    base = Path(platform_config_file).resolve().parent
    domains_dir = base / "domains"
    templates_dir = base / "templates" / "en"
    if not domains_dir.is_dir():
        return []
    registry = default_event_registry()
    problems: list[str] = []
    for template_file in sorted(domains_dir.glob("*.yaml")):
        try:
            template = load_domain_template(template_file)
        except DomainTemplateError as exc:
            problems.append(f"{template_file.name}: {exc.path}: {exc.message}")
            continue
        for problem in validate_automations(
            template, known_channels=set(BUILTIN_CHANNELS), registry=registry, templates_dir=templates_dir
        ):
            problems.append(f"{template_file.name}: {problem}")
    return problems
