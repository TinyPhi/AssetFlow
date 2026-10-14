# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Registered event types and their fields (§B7.3, §B7.4).

A condition or a recipient reference may only name a field the event type actually carries; this
is checked once at config load, never at runtime, so a typo in a domain template stops the boot
instead of silently never matching.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EventSpec:
    """One registered event type: its data fields and, if it has one, its holder field."""

    fields: frozenset[str]
    holder_field: str | None = None
    personal_fields: frozenset[str] = frozenset()  # fields that identify a person (§B6.3 rule 3)


@dataclass
class EventFieldRegistry:
    """Event type -> `EventSpec`. One registry per process; built once at startup."""

    _events: dict[str, EventSpec] = field(default_factory=dict)

    def register_event(
        self,
        event_type: str,
        fields: set[str] | frozenset[str],
        *,
        holder_field: str | None = None,
        personal_fields: set[str] | frozenset[str] = frozenset(),
    ) -> None:
        """Register `event_type`'s data fields, and which one (if any) names the notice's holder.

        `personal_fields` (a subset of `fields`) are dropped from an outbound payload unless the
        installation allows personal data.
        """
        if event_type in self._events:
            raise ValueError(f"event {event_type!r} is already registered")
        frozen = frozenset(fields)
        if holder_field is not None and holder_field not in frozen:
            raise ValueError(
                f"event {event_type!r}: holder_field {holder_field!r} is not one of its own fields"
            )
        if not frozenset(personal_fields) <= frozen:
            raise ValueError(f"event {event_type!r}: personal_fields must be among its fields")
        self._events[event_type] = EventSpec(frozen, holder_field, frozenset(personal_fields))

    def get(self, event_type: str) -> EventSpec | None:
        """Return the spec of `event_type`, or None if nothing is registered for it."""
        return self._events.get(event_type)

    def known_event_types(self) -> list[str]:
        """Every event type with a registered spec (for subscribing the automation handler)."""
        return list(self._events)
