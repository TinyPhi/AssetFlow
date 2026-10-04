# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Notification templates: `config/templates/<lang>/<key>.{html,txt}` (§B6.3 rule 3, §C1.6).

Each template's front matter declares the event fields it uses (``fields: [...]``); rendering
passes only those fields, never the whole event payload, so a template cannot leak a field it did
not declare (payload minimization).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined, Template

__all__ = ["TemplateError", "TemplateSet", "load_template_set"]

_FRONT_MATTER_DELIMITER = "---"


class TemplateError(Exception):
    """A template file is missing or malformed."""


def _split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith(_FRONT_MATTER_DELIMITER):
        return {}, text
    lines = text.splitlines(keepends=True)
    end = next((i for i in range(1, len(lines)) if lines[i].rstrip() == _FRONT_MATTER_DELIMITER), None)
    if end is None:
        return {}, text
    front_matter = yaml.safe_load("".join(lines[1:end])) or {}
    body = "".join(lines[end + 1 :])
    return front_matter, body


class TemplateSet:
    """One template key's declared fields and compiled bodies, for one or more formats."""

    def __init__(self, fields: frozenset[str], compiled: dict[str, Template]) -> None:
        self.fields = fields
        self._compiled = compiled

    def formats(self) -> list[str]:
        """Every format this template key has (`html`, `txt`)."""
        return list(self._compiled)

    def render(self, fmt: str, data: dict[str, Any]) -> str:
        """Render `fmt`, passing only this template's own declared fields from `data`."""
        if fmt not in self._compiled:
            raise TemplateError(f"template has no {fmt!r} format")
        scoped = {name: data.get(name) for name in self.fields}
        return self._compiled[fmt].render(**scoped)


def _environment(templates_dir: Path, *, autoescape: bool) -> Environment:
    return Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=autoescape,  # noqa: S701 - .txt is deliberately not auto-escaped (load_template_set)
        undefined=StrictUndefined,
    )


def load_template_set(templates_dir: Path, key: str) -> TemplateSet:
    """Load every format of `key` under `templates_dir` (one language directory, e.g. `en`).

    `.html` is auto-escaped (Jinja2's default protection against injecting markup from event
    data); `.txt` is not, so plain-text output never shows literal HTML entities.
    """
    compiled: dict[str, Template] = {}
    fields: frozenset[str] | None = None
    for fmt, autoescape in (("html", True), ("txt", False)):
        path = templates_dir / f"{key}.{fmt}"
        if not path.exists():
            continue
        front_matter, body = _split_front_matter(path.read_text(encoding="utf-8"))
        these_fields = frozenset(front_matter.get("fields", []))
        if fields is None:
            fields = these_fields
        elif fields != these_fields:
            raise TemplateError(f"template {key!r}: {fmt} declares different fields than another format")
        compiled[fmt] = _environment(templates_dir, autoescape=autoescape).from_string(body)
    if not compiled:
        raise TemplateError(f"template {key!r} not found under {templates_dir}")
    return TemplateSet(fields or frozenset(), compiled)
