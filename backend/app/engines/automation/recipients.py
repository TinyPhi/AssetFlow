# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Resolve a rule's recipients against one event (§B6.3 "Recipient resolution", M1.5-T2).

Only `holder`, `actor`, `team:<field>` and `role:<role>@<scope>` are resolved here (§B6.3's
`assignee`, `requester`, `team_lead` and `org_unit_manager` keywords are rejected at config load,
§engines.automation.models, until the module that owns them registers them).
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.core.permissions import ScopeType
from app.engines.automation.models import AutomationRule, RecipientRef

__all__ = ["Directory", "resolve"]


class Directory(Protocol):
    """What the resolver needs to know about an organization's members, teams and grants."""

    async def team_member_ids(self, team_id: UUID) -> set[UUID]:
        """Active members of `team_id` right now."""
        ...

    async def members_with_role(
        self, role_key: str, scope_type: ScopeType, scope_id: UUID | None
    ) -> set[UUID]:
        """Members holding `role_key` through a grant covering `scope_id` at `scope_type`.

        A grant at a parent org unit covers every org unit under it (§B5); `scope_id` is the
        *target* org unit or team, not the grant's own scope id.
        """
        ...

    async def is_active(self, member_id: UUID) -> bool:
        """Whether `member_id` may still be notified (not suspended, not left)."""
        ...


def _as_uuid(value: object) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:
            return None
    return None


async def _resolve_one(
    ref: RecipientRef, event_data: dict[str, object], holder_field: str | None, directory: Directory
) -> set[UUID]:
    if ref.kind == "holder":
        member_id = _as_uuid(event_data.get(holder_field)) if holder_field else None
        return {member_id} if member_id is not None else set()
    if ref.kind == "actor":
        # Optional: most organization events do not carry an actor in their outbox payload today
        # (see this plan's Record) - not every event has one to resolve.
        member_id = _as_uuid(event_data.get("actor_member_id"))
        return {member_id} if member_id is not None else set()
    if ref.kind == "team":
        team_id = _as_uuid(event_data.get(ref.team_field)) if ref.team_field else None
        return await directory.team_member_ids(team_id) if team_id is not None else set()
    # The only remaining kind is "role".
    if ref.scope == "organization":
        return await directory.members_with_role(ref.role_key or "", ScopeType.ORGANIZATION, None)
    scope_type = ScopeType.ORG_UNIT if ref.scope == "org_unit" else ScopeType.TEAM
    scope_id = _as_uuid(event_data.get(ref.scope_field)) if ref.scope_field else None
    if scope_id is None:
        return set()
    return await directory.members_with_role(ref.role_key or "", scope_type, scope_id)


async def resolve(
    event_data: dict[str, object], rule: AutomationRule, *, holder_field: str | None, directory: Directory
) -> set[UUID]:
    """The active member ids `rule.then.recipients` names for this event; suspended members dropped."""
    resolved: set[UUID] = set()
    for ref in rule.then.recipients:
        resolved |= await _resolve_one(ref, event_data, holder_field, directory)
    active: set[UUID] = set()
    for member_id in resolved:
        if await directory.is_active(member_id):
            active.add(member_id)
    return active
