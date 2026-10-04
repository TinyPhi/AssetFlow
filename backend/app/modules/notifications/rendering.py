# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Render a notification from its template (§B6.3 rule 3, payload minimization).

A template declares the event fields it uses; only those are ever stored with a pending delivery
and only those reach the renderer, so a template cannot leak a field it did not declare.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from app.channels.base import RenderedMessage
from app.channels.templates import load_template_set

__all__ = ["TEMPLATES_DIR", "minimized_data", "render_message"]

#: `config/templates/en/` relative to the repository root (this file: backend/app/modules/notifications/).
TEMPLATES_DIR = Path(__file__).resolve().parents[4] / "config" / "templates" / "en"


def minimized_data(template_key: str, event_data: dict[str, Any]) -> dict[str, Any]:
    """Only the fields `template_key` declares, taken from `event_data`."""
    template = load_template_set(TEMPLATES_DIR, template_key)
    return {name: event_data[name] for name in sorted(template.fields) if name in event_data}


def render_message(
    template_key: str, event_type: str, event_id: UUID, data: dict[str, Any]
) -> RenderedMessage:
    """Render every format `template_key` has: `subject` from the text form, `body` from the HTML."""
    template = load_template_set(TEMPLATES_DIR, template_key)
    return RenderedMessage(
        subject=template.render("txt", data) if "txt" in template.formats() else "",
        body=template.render("html", data) if "html" in template.formats() else "",
        data={"event_type": event_type, "event_id": str(event_id), "template_key": template_key},
    )
