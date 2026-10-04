# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The published-events catalogue stays complete (§C7.2): every written event is listed."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from app.engines.automation.registry import default_registry
from app.modules.notifications.events import NOTIFICATION_EVENTS

BACKEND = Path(__file__).resolve().parents[2]
#: errors.py holds error codes and events.py is the catalogue itself; neither publishes an event.
_NOT_SOURCES = {"errors.py", "events.py"}
SOURCES = [
    *sorted(
        p for p in (BACKEND / "app" / "modules" / "notifications").glob("*.py") if p.name not in _NOT_SOURCES
    ),
    BACKEND / "workers" / "notification_sender.py",
]
EVENT_NAME = re.compile(r"^notification(?:_[a-z]+)?\.[a-z_]+$")


def _literals(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def _published() -> set[str]:
    found: set[str] = set()
    for path in SOURCES:
        found |= {s for s in _literals(path) if EVENT_NAME.match(s)}
    return found


def test_every_published_event_is_catalogued() -> None:
    published = _published()
    assert published <= set(NOTIFICATION_EVENTS), sorted(published - set(NOTIFICATION_EVENTS))


def test_every_catalogued_event_is_still_published() -> None:
    assert set(NOTIFICATION_EVENTS) <= _published()


def test_the_catalogue_has_no_automation_event_in_it() -> None:
    assert not set(NOTIFICATION_EVENTS) & set(default_registry().known_event_types())


def test_every_entry_describes_itself() -> None:
    for name, event in NOTIFICATION_EVENTS.items():
        assert event.description.endswith("."), name
        assert event.fields, name
        assert event.aggregate_type, name
