# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Turn one event into notification intents (§B6.3 rule 8 idempotency, M1.5-T2)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import UUID

from app.engines.automation.conditions import evaluate
from app.engines.automation.models import AutomationRule
from app.engines.automation.recipients import Directory, resolve
from app.engines.automation.registry import EventFieldRegistry

__all__ = ["NotificationIntent", "filter_by_preferences", "plan"]


@dataclass(frozen=True)
class NotificationIntent:
    """One (event, recipient, channel) notification to send.

    `event_type` and `event_data` travel with the intent because a channel renders its template at
    send time (P6-03), not at plan time: the planner only decides *who* gets notified *how*, never
    *what the text says*.
    """

    event_id: UUID
    organization_id: UUID
    member_id: UUID
    channel_key: str
    template_key: str
    idempotency_key: str
    event_type: str
    event_data: dict[str, object]
    entity_type: str | None = None
    entity_id: UUID | None = None


def _idempotency_key(event_id: UUID, member_id: UUID, channel_key: str) -> str:
    # §B6.3 rule 8: one idempotency key per (event, recipient, channel).
    raw = f"{event_id}|{member_id}|{channel_key}".encode()
    return hashlib.sha256(raw).hexdigest()


async def plan(
    *,
    event_id: UUID,
    organization_id: UUID,
    event_type: str,
    event_data: dict[str, object],
    rules: list[AutomationRule],
    registry: EventFieldRegistry,
    directory: Directory,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
) -> list[NotificationIntent]:
    """Every notification intent `rules` produce for one event; `rules` not matching are skipped."""
    spec = registry.get(event_type)
    holder_field = spec.holder_field if spec is not None else None
    intents: list[NotificationIntent] = []
    for rule in rules:
        if rule.when != event_type:
            continue
        if not evaluate(rule.if_, event_data):
            continue
        member_ids = await resolve(event_data, rule, holder_field=holder_field, directory=directory)
        for member_id in sorted(member_ids):
            for channel_key in rule.then.channels:
                intents.append(
                    NotificationIntent(
                        event_id=event_id,
                        organization_id=organization_id,
                        member_id=member_id,
                        channel_key=channel_key,
                        template_key=rule.then.template,
                        idempotency_key=_idempotency_key(event_id, member_id, channel_key),
                        event_type=event_type,
                        event_data=event_data,
                        entity_type=entity_type,
                        entity_id=entity_id,
                    )
                )
    return filter_by_preferences(intents)


def filter_by_preferences(intents: list[NotificationIntent]) -> list[NotificationIntent]:
    """Hook for P6-07's member preferences; identity until then."""
    return intents
