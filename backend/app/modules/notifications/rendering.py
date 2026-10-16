# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Render a notification from its template (§B6.3 rule 3, payload minimization).

A template declares the event fields it uses; only those are ever stored with a pending delivery
and only those reach the renderer, so a template cannot leak a field it did not declare. Fields it
marks personal are left out unless the caller allows personal data. A language without the
template falls back to `en`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from app.channels.base import RenderedMessage
from app.channels.templates import TemplateError, TemplateSet, load_template_set

__all__ = ["TEMPLATES_DIR", "minimized_data", "render_message"]

#: `config/templates/en/` relative to the repository root (this file: backend/app/modules/notifications/).
#: Other languages are sibling directories (`config/templates/<lang>/`).
TEMPLATES_DIR = Path(__file__).resolve().parents[4] / "config" / "templates" / "en"


def _load(template_key: str, language: str) -> TemplateSet:
    if language and language != TEMPLATES_DIR.name:
        try:
            return load_template_set(TEMPLATES_DIR.parent / language, template_key)
        except (TemplateError, OSError):
            pass  # not translated: fall back to the default language
    return load_template_set(TEMPLATES_DIR, template_key)


def minimized_data(
    template_key: str, event_data: dict[str, Any], *, allow_personal: bool = True
) -> dict[str, Any]:
    """Only the fields `template_key` declares, taken from `event_data` (no personal field unless allowed)."""
    template = load_template_set(TEMPLATES_DIR, template_key)
    return {
        name: event_data[name]
        for name in sorted(template.fields)
        if name in event_data and (allow_personal or name not in template.personal_fields)
    }


def render_message(
    template_key: str,
    event_type: str,
    event_id: UUID,
    data: dict[str, Any],
    *,
    allow_personal: bool = True,
    language: str = "en",
    fields: dict[str, Any] | None = None,
) -> RenderedMessage:
    """Render every format `template_key` has: `body` is the HTML, `text` the plain text.

    `subject` is the template's own subject line when it declares one, otherwise the plain text.
    """
    template = _load(template_key, language)
    text = template.render("txt", data, allow_personal=allow_personal) if "txt" in template.formats() else ""
    has_html = "html" in template.formats()
    html = template.render("html", data, allow_personal=allow_personal) if has_html else ""
    subject = template.render_subject(data, allow_personal=allow_personal) or text
    return RenderedMessage(
        subject=subject,
        body=html,
        text=text,
        data={
            "event_type": event_type,
            "event_id": str(event_id),
            "template_key": template_key,
            "fields": dict(fields or {}),  # what the pending delivery stored for this channel
        },
    )
