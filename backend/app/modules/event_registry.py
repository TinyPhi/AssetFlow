# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The event types automations can react to, composed from the modules that publish them (§B7.3).

The automation engine knows nothing about specific modules (§B4.2 rule 5): it only provides the
`EventFieldRegistry` class. This module, one layer up, asks each module for its events.
"""

from __future__ import annotations

from app.engines.automation.registry import EventFieldRegistry
from app.modules.organization import events as org_events

__all__ = ["default_event_registry"]


def default_event_registry() -> EventFieldRegistry:
    """The event types known at startup: each module that opted in registers its own."""
    registry = EventFieldRegistry()
    _register_organization_events(registry)
    return registry


def _register_organization_events(registry: EventFieldRegistry) -> None:
    """Organization-structure events (`app.modules.organization.events`), M1.4.

    Only `team_member.added` carries a usable holder today (the member who was added); the other
    organization events have no natural holder and no actor in their outbox payload yet (the
    organization module's existing INSERT statements write only the entity's own fields - see the
    Record for this plan). They are still registered, with no holder, so their fields are at least
    available to `if` conditions and `team:`/`role:...@org_unit:`/`role:...@team:` recipients.
    """
    # Field sets below are the exact outbox `payload` keys each event is published with
    # (app.modules.organization.service), not just the (differently shaped) Pydantic event model
    # in app.modules.organization.events - the two were never required to match and do not always.
    registry.register_event(org_events.ORG_UNIT_CREATED, {"id", "code", "path", "parent_id"})
    registry.register_event(org_events.ORG_UNIT_UPDATED, {"id", "name", "type"})
    registry.register_event(org_events.ORG_UNIT_MOVED, {"id", "old_path", "new_path", "new_parent_id"})
    registry.register_event(org_events.ORG_UNIT_ARCHIVED, {"id", "code"})
    registry.register_event(org_events.LOCATION_CREATED, {"id", "code", "path", "parent_id"})
    registry.register_event(org_events.LOCATION_UPDATED, {"id", "name", "type"})
    registry.register_event(org_events.LOCATION_MOVED, {"id", "old_path", "new_path", "new_parent_id"})
    registry.register_event(org_events.LOCATION_DELETED, {"id", "code"})
    registry.register_event(org_events.TEAM_CREATED, {"id", "code", "name", "type"})
    registry.register_event(org_events.TEAM_UPDATED, {"id", "name", "type"})
    registry.register_event(org_events.TEAM_ARCHIVED, {"id", "code"})
    registry.register_event(
        org_events.TEAM_MEMBER_ADDED,
        {"id", "team_id", "member_id", "team_role"},
        holder_field="member_id",
    )
    registry.register_event(org_events.TEAM_MEMBER_UPDATED, {"id", "team_id", "member_id", "team_role"})
    registry.register_event(org_events.TEAM_MEMBER_REMOVED, {"team_id", "member_id"})
