# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The declarative field mapping behind a webhook payload (§B6.3 webhook settings, §B7.3).

An organization maps *target payload paths* (dotted, for example `asset.name`) to *source fields* of
the event types it listens to. Only mapped fields are ever sent. A source that the event does not
carry is rejected when the settings are saved, never at send time. Fields an event type marks as
personal are dropped unless the installation allows personal data (§B6.3 rule 3).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any, Protocol

__all__ = ["RESERVED_KEYS", "EventCatalog", "build_payload", "canonical_json", "mapping_problems"]


class EventSpecLike(Protocol):
    """What the mapping needs to know about one event type."""

    fields: frozenset[str]
    personal_fields: frozenset[str]


class EventCatalog(Protocol):
    """Looks an event type up; the automation event registry satisfies it."""

    def get(self, event_type: str) -> EventSpecLike | None: ...


#: Always sent by the channel itself; a mapping may not claim them.
RESERVED_KEYS = frozenset({"event_type", "event_id", "occurred_at", "organization_id"})
_TARGET = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")


def mapping_problems(
    mapping: Mapping[str, str], events: list[str], registry: EventCatalog
) -> list[tuple[str, str]]:
    """Every problem with `mapping` for `events`, as `(path, message)` pairs (empty when valid)."""
    problems: list[tuple[str, str]] = []
    specs = {event: registry.get(event) for event in events}
    for event, spec in specs.items():
        if spec is None:
            problems.append(("events", f"{event!r} is not a registered event type"))
    known = [spec for spec in specs.values() if spec is not None]
    targets = sorted(mapping)
    for target in targets:
        source = mapping[target]
        path = f"field_mapping.{target}"
        if _TARGET.match(target) is None:
            problems.append((path, "the target must be a dotted path of plain names"))
            continue
        if target.split(".", 1)[0] in RESERVED_KEYS:
            problems.append((path, "this key is always sent by AssetFlow and cannot be mapped"))
        for other in targets:
            if other != target and other.startswith(target + "."):
                problems.append((path, f"conflicts with the deeper target {other!r}"))
        missing = [e for e, spec in specs.items() if spec is not None and source not in spec.fields]
        if known and missing:
            problems.append((path, f"{source!r} is not a field of {', '.join(sorted(missing))}"))
    return problems


def _set_path(root: dict[str, Any], target: str, value: Any) -> None:
    *parents, leaf = target.split(".")
    node = root
    for part in parents:
        node = node.setdefault(part, {})
    node[leaf] = value


def build_payload(
    mapping: Mapping[str, str],
    event_data: Mapping[str, Any],
    *,
    personal_fields: frozenset[str],
    allow_personal: bool,
) -> dict[str, Any]:
    """The mapped fields of one event, nested by target path; no mapped field means nothing is sent."""
    payload: dict[str, Any] = {}
    for target in sorted(mapping):
        source = mapping[target]
        if source not in event_data or (source in personal_fields and not allow_personal):
            continue
        _set_path(payload, target, event_data[source])
    return payload


def canonical_json(value: Any) -> bytes:
    """The one serialization that is both signed and sent: sorted keys, no spaces, UTF-8."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
