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

from pathlib import Path
from typing import TYPE_CHECKING

from app.core.db import Connection
from app.core.domain_template import DomainTemplateError, load_domain_template
from app.engines.automation.directory_pg import PgDirectory
from app.engines.automation.planner import plan
from app.engines.automation.registry import EventFieldRegistry, default_registry
from app.modules.notifications.dispatch import enqueue

if TYPE_CHECKING:
    # A lazy annotation only (see `from __future__ import annotations`): importing the concrete
    # type at runtime would make workers.subscribers and app.engines.automation import each other.
    from workers.subscribers import OutboxEvent, SubscriberRegistry

__all__ = ["CONSUMER", "handle", "register"]

CONSUMER = "automation"

#: `config/domains/` relative to the repository root (this file: backend/app/engines/automation/).
DOMAINS_DIR = Path(__file__).resolve().parents[4] / "config" / "domains"


async def handle(conn: Connection, event: OutboxEvent, *, registry: EventFieldRegistry | None = None) -> None:
    """Plan and enqueue the notifications `event` triggers, for its organization's domain template."""
    domain_key = await conn.fetchval(
        "SELECT domain_key FROM public.organizations WHERE id = $1", event.organization_id
    )
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
        registry=registry or default_registry(),
        directory=directory,
    )
    await enqueue(conn, intents)


def register(subscriber_registry: SubscriberRegistry, event_registry: EventFieldRegistry) -> None:
    """Subscribe `handle` to every event type `event_registry` knows."""
    for event_type in event_registry.known_event_types():
        subscriber_registry.subscribe(event_type, CONSUMER, handle)
