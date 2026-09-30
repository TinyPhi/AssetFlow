# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""EventBusProvider interface (§B6.1, §B6.2), INTERFACE_VERSION 1.0.

Every event is tenant-scoped: ``publish`` takes the ``organization_id`` (§B6.1 rule 8).
``subscribe(topic, handler, group)``: within one group each event reaches one handler.
Implementations (``postgres``, ``inmemory`` or a third-party entry point) pass the shared suite
in ``tests/contract/events/``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any

EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class EventBusProvider(ABC):
    """Event bus provider."""

    INTERFACE_VERSION: str = "1.0"

    @property
    def name(self) -> str:
        """Provider implementation identifier."""
        return self.__class__.__name__

    @abstractmethod
    async def publish(self, topic: str, event: dict[str, Any], organization_id: str) -> None:
        """Publish one tenant-scoped event."""

    @abstractmethod
    async def subscribe(self, topic: str, handler: EventHandler, group: str | None = None) -> None:
        """Register ``handler`` for ``topic``; ``group`` defaults to one group per handler."""

    @abstractmethod
    async def health(self) -> dict[str, Any]:
        """Return ``{"status": ...}``."""


#: Earlier name, kept so existing imports keep working.
EventsProvider = EventBusProvider
