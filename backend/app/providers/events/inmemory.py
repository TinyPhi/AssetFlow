# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""``inmemory`` event bus: tests and single-process development only (§B6.2).

Delivery is synchronous inside ``publish``. Within one subscriber group, handlers take turns
(round robin). A failing handler does not stop delivery to other groups: the failure is logged
with its traceback and counted, and ``health()`` reports ``degraded`` until a later publish delivers
without failures.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.providers.context import ProviderContext, ProviderSettings, parse_settings
from app.providers.events.base import EventBusProvider, EventHandler

logger = logging.getLogger(__name__)


class InMemoryEventsSettings(ProviderSettings):
    """``providers.events.settings`` for ``type: inmemory`` (none yet)."""


@dataclass
class _Group:
    handlers: list[EventHandler] = field(default_factory=list)
    turn: int = 0

    def next_handler(self) -> EventHandler:
        handler = self.handlers[self.turn % len(self.handlers)]
        self.turn += 1
        return handler


class InMemoryEventBusProvider(EventBusProvider):
    """Publish/subscribe inside one process."""

    def __init__(self) -> None:
        self._topics: dict[str, dict[str, _Group]] = {}
        self._published = 0
        self._failed = 0
        self._last_failure: str | None = None

    @classmethod
    def from_settings(cls, settings: dict[str, Any], context: ProviderContext) -> InMemoryEventBusProvider:
        """Registry factory."""
        parse_settings(InMemoryEventsSettings, settings, context)
        return cls()

    async def publish(self, topic: str, event: dict[str, Any], organization_id: str) -> None:
        """Deliver to one handler of every group subscribed to ``topic``."""
        if not organization_id:
            raise ValueError("organization_id is required for every event")
        envelope = {"topic": topic, "organization_id": organization_id, "payload": event}
        self._published += 1
        failure: str | None = None
        groups = list(self._topics.get(topic, {}).items())
        for group_name, group in groups:
            handler = group.next_handler()
            try:
                await handler(envelope)
            except Exception as exc:  # a handler bug must not stop other groups; logged and counted
                self._failed += 1
                failure = type(exc).__name__
                logger.exception("event handler failed (topic=%s, group=%s)", topic, group_name)
        if groups:
            self._last_failure = failure

    async def subscribe(self, topic: str, handler: EventHandler, group: str | None = None) -> None:
        """Register ``handler``; with no group it gets its own group."""
        groups = self._topics.setdefault(topic, {})
        key = group if group is not None else f"_handler_{id(handler)}_{len(groups)}"
        groups.setdefault(key, _Group()).handlers.append(handler)

    async def health(self) -> dict[str, Any]:
        """Counts only; ``degraded`` while the most recent delivery failed."""
        return {
            "status": "degraded" if self._last_failure else "healthy",
            "provider": "inmemory",
            "published": self._published,
            "handler_failures": self._failed,
            "last_failure": self._last_failure,
        }


#: Earlier name, kept so existing imports keep working.
InMemoryEventsProvider = InMemoryEventBusProvider
