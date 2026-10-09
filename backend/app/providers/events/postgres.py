# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""PostgreSQL transactional outbox event bus provider (§B6.1, §B6.2, M1.3-T11).

Supports transactional outbox events with LISTEN/NOTIFY wakeup and subscriber groups.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

import asyncpg

from app.core.db import get_db_pool
from app.providers.context import ProviderContext, ProviderSettings, parse_settings
from app.providers.events.base import EventBusProvider, EventHandler

logger = logging.getLogger(__name__)


class PostgresEventsSettings(ProviderSettings):
    """``providers.events.settings`` for ``type: postgres``."""

    notify_channel: str = "outbox_events"
    batch_size: int = 100
    poll_interval_seconds: float = 2.0


@dataclass
class _SubscriberGroup:
    handlers: list[EventHandler] = field(default_factory=list)
    turn: int = 0

    def next_handler(self) -> EventHandler:
        handler = self.handlers[self.turn % len(self.handlers)]
        self.turn += 1
        return handler


class PostgresEventBusProvider(EventBusProvider):
    """Transactional outbox event bus over PostgreSQL (§B6.2, M1.3-T11)."""

    def __init__(self, settings: PostgresEventsSettings, context: ProviderContext) -> None:
        self.settings = settings
        self.context = context
        self._topics: dict[str, dict[str, _SubscriberGroup]] = {}
        self._published = 0
        self._failed = 0
        self._last_failure: str | None = None

    @classmethod
    def from_settings(cls, settings: dict[str, Any], context: ProviderContext) -> PostgresEventBusProvider:
        """Registry factory."""
        parsed = parse_settings(PostgresEventsSettings, settings, context)
        return cls(parsed, context)

    async def publish(self, topic: str, event: dict[str, Any], organization_id: str) -> None:
        """Publish one tenant-scoped event."""
        if not organization_id:
            raise ValueError("organization_id is required for every event")

        envelope = {"topic": topic, "organization_id": organization_id, "payload": event}
        self._published += 1

        # 1. Wake the worker dispatcher over NOTIFY. The payload is an opaque wake-up id only: the
        # event itself stays in the outbox, inside its tenant transaction (AF-008, §B9.3).
        pool = get_db_pool()
        if pool is not None:
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        "SELECT pg_notify($1, $2)", self.settings.notify_channel, uuid.uuid4().hex
                    )
            except (asyncpg.PostgresError, OSError) as exc:
                logger.warning("Postgres NOTIFY failed: %s", type(exc).__name__)

        # 2. Dispatch to registered local handlers (one per group)
        failure: str | None = None
        groups = list(self._topics.get(topic, {}).items())
        for group_name, group in groups:
            handler = group.next_handler()
            try:
                await handler(envelope)
            except Exception as exc:
                self._failed += 1
                failure = type(exc).__name__
                logger.exception("Event handler failed in group %s for topic %s", group_name, topic)

        if groups:
            self._last_failure = failure

    async def subscribe(self, topic: str, handler: EventHandler, group: str | None = None) -> None:
        """Register handler for topic within a subscriber group."""
        groups = self._topics.setdefault(topic, {})
        key = group if group is not None else f"_handler_{id(handler)}_{len(groups)}"
        groups.setdefault(key, _SubscriberGroup()).handlers.append(handler)

    async def health(self) -> dict[str, Any]:
        """Health status of PostgreSQL event bus."""
        pool = get_db_pool()
        db_status = "connected" if pool is not None else "standby"
        return {
            "status": "degraded" if self._last_failure else "healthy",
            "provider": "postgres",
            "database": db_status,
            "published": self._published,
            "handler_failures": self._failed,
            "last_failure": self._last_failure,
        }
