# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The outbox subscriber that turns an organization's own events into notification intents (§B6.3,
§B9.3, M1.5-T2).

Reads the organization's domain template fresh on every call (no cache yet - "later plans register
theirs" is this phase's general pattern for infrastructure nothing else needs until it is built).
A missing or invalid template is not a subscriber failure: it is a boot-time problem that
`assetflow config validate` catches, so this subscriber skips quietly rather than retrying forever.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from app.core.db import Connection
from app.engines.automation.directory_pg import PgDirectory
from app.engines.automation.domain_template import DomainTemplateError, load_domain_template
from app.engines.automation.planner import NotificationIntent, plan
from app.engines.automation.preferences_pg import PgPreferences
from app.engines.automation.registry import EventFieldRegistry

if TYPE_CHECKING:
    # A lazy annotation only (see `from __future__ import annotations`): importing the concrete
    # type at runtime would make workers.subscribers and app.engines.automation import each other.
    from workers.subscribers import OutboxEvent, SubscriberRegistry

__all__ = ["CONSUMER", "handle", "mandatory_inapp_events", "register"]

CONSUMER = "automation"

#: Sends or queues planned intents (the notification module provides it).
Enqueue = Callable[[Connection, list[NotificationIntent]], Awaitable[None]]

#: `config/domains/` relative to the repository root (this file: backend/app/engines/automation/).
DOMAINS_DIR = Path(__file__).resolve().parents[4] / "config" / "domains"


def mandatory_inapp_events(domain_key: str) -> set[str]:
    """Event types for which this domain template's rules make the in-app notice mandatory.

    A member cannot switch in-app off for these (§B6.3 rule 7); an unreadable template means none.
    """
    template_path = DOMAINS_DIR / f"{domain_key}.yaml"
    if not template_path.exists():
        return set()
    try:
        template = load_domain_template(template_path)
    except DomainTemplateError:
        return set()
    return {r.when for r in template.automations if r.then.mandatory and "inapp" in r.then.channels}


async def handle(
    conn: Connection, event: OutboxEvent, *, registry: EventFieldRegistry, enqueue: Enqueue
) -> None:
    """Plan and enqueue the notifications `event` triggers, for its organization's domain template.

    `registry` (the events rules may use) and `enqueue` (what sends or queues an intent) are given by
    the caller: the engine knows neither the modules that publish events nor the one that delivers.
    """
    domain_key = await conn.fetchval("SELECT platform.get_domain_key($1)", event.organization_id)
    if not domain_key:
        return
    template_path = DOMAINS_DIR / f"{domain_key}.yaml"
    if not template_path.exists():
        return
    try:
        template = load_domain_template(template_path)
    except DomainTemplateError:
        return
    directory = PgDirectory(conn)
    intents = await plan(
        event_id=event.id,
        organization_id=event.organization_id,
        event_type=event.event_type,
        event_data=event.payload,
        rules=template.automations,
        registry=registry,
        directory=directory,
        entity_type=event.aggregate_type,
        entity_id=event.aggregate_id,
        occurred_at=event.occurred_at,
        preferences=PgPreferences(conn),
    )
    await enqueue(conn, intents)


def register(
    subscriber_registry: SubscriberRegistry, event_registry: EventFieldRegistry, enqueue: Enqueue
) -> None:
    """Subscribe `handle` to every event type `event_registry` knows."""
    handler = partial(handle, registry=event_registry, enqueue=enqueue)
    for event_type in event_registry.known_event_types():
        subscriber_registry.subscribe(event_type, CONSUMER, handler)
