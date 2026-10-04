# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Subscribers of outbox events (§B6.2, §B9.3).

A subscriber is a named consumer of one event type. The dispatcher runs it inside its own
transaction under the event's organization, after recording `(consumer, event)` in
`processed_events`. If the subscriber raises, that transaction rolls back, including the record, so
the next attempt runs it again; if it succeeds, a repeated delivery of the same event is skipped.
A subscriber therefore does its database work on the connection it is given and never makes a
network call; side effects that leave the system are written as rows that a later job sends.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from app.core.db import Connection
from app.engines.automation import registry as automation_registry
from app.engines.automation import subscriber as automation_subscriber


@dataclass(frozen=True)
class OutboxEvent:
    """One claimed outbox row. `payload` is the domain event body (§C1.6)."""

    id: UUID
    organization_id: UUID
    event_type: str
    aggregate_type: str
    aggregate_id: UUID
    payload: dict[str, Any]
    attempts: int
    occurred_at: datetime | None = None  # when the event was written to the outbox


SubscriberHandler = Callable[[Connection, OutboxEvent], Awaitable[None]]


@dataclass(frozen=True)
class Subscription:
    """A consumer name (the idempotency key together with the event id) and its handler."""

    consumer: str
    handler: SubscriberHandler


@dataclass
class SubscriberRegistry:
    """Event type -> subscriptions. Consumer names are unique per event type."""

    _by_type: dict[str, list[Subscription]] = field(default_factory=dict)

    def subscribe(self, event_type: str, consumer: str, handler: SubscriberHandler) -> None:
        """Register `handler` as `consumer` for `event_type`."""
        existing = self._by_type.setdefault(event_type, [])
        if any(sub.consumer == consumer for sub in existing):
            raise ValueError(f"consumer {consumer!r} is already subscribed to {event_type!r}")
        existing.append(Subscription(consumer, handler))

    def for_event(self, event_type: str) -> list[Subscription]:
        """Return the subscriptions of one event type (empty when nobody listens)."""
        return list(self._by_type.get(event_type, ()))


def default_registry() -> SubscriberRegistry:
    """The subscribers of the running worker."""
    registry = SubscriberRegistry()
    automation_subscriber.register(registry, automation_registry.default_registry())
    return registry
