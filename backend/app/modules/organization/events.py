# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Organization structure domain event definitions (§B9.3, §C4.1, M1.4-T4)."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

__all__ = [
    "LOCATION_CREATED",
    "LOCATION_DELETED",
    "LOCATION_MOVED",
    "LOCATION_UPDATED",
    "ORG_UNIT_ARCHIVED",
    "ORG_UNIT_CREATED",
    "ORG_UNIT_MOVED",
    "ORG_UNIT_UPDATED",
    "TEAM_ARCHIVED",
    "TEAM_CREATED",
    "TEAM_MEMBER_ADDED",
    "TEAM_MEMBER_REMOVED",
    "TEAM_MEMBER_UPDATED",
    "TEAM_UPDATED",
    "LocationCreatedEvent",
    "LocationDeletedEvent",
    "LocationMovedEvent",
    "LocationUpdatedEvent",
    "OrgUnitArchivedEvent",
    "OrgUnitCreatedEvent",
    "OrgUnitMovedEvent",
    "OrgUnitUpdatedEvent",
    "TeamArchivedEvent",
    "TeamCreatedEvent",
    "TeamMemberAddedEvent",
    "TeamMemberRemovedEvent",
    "TeamMemberUpdatedEvent",
    "TeamUpdatedEvent",
]

ORG_UNIT_CREATED = "org_unit.created"
ORG_UNIT_UPDATED = "org_unit.updated"
ORG_UNIT_MOVED = "org_unit.moved"
ORG_UNIT_ARCHIVED = "org_unit.archived"

LOCATION_CREATED = "location.created"
LOCATION_UPDATED = "location.updated"
LOCATION_MOVED = "location.moved"
LOCATION_DELETED = "location.deleted"

TEAM_CREATED = "team.created"
TEAM_UPDATED = "team.updated"
TEAM_ARCHIVED = "team.archived"

TEAM_MEMBER_ADDED = "team_member.added"
TEAM_MEMBER_UPDATED = "team_member.updated"
TEAM_MEMBER_REMOVED = "team_member.removed"


class OrgUnitCreatedEvent(BaseModel):
    id: UUID = Field(description="Created organizational unit ID")
    code: str = Field(description="Organizational unit code")
    path: str = Field(description="Materialized ltree path")
    parent_id: UUID | None = Field(description="Parent unit ID")


class OrgUnitUpdatedEvent(BaseModel):
    id: UUID = Field(description="Updated organizational unit ID")
    name: str = Field(description="Current unit name")
    type: str = Field(description="Current unit type")


class OrgUnitMovedEvent(BaseModel):
    id: UUID = Field(description="Moved organizational unit ID")
    old_path: str = Field(description="Previous ltree path")
    new_path: str = Field(description="New ltree path")
    new_parent_id: UUID | None = Field(description="New parent unit ID")


class OrgUnitArchivedEvent(BaseModel):
    id: UUID = Field(description="Archived organizational unit ID")
    code: str = Field(description="Organizational unit code")


class LocationCreatedEvent(BaseModel):
    id: UUID = Field(description="Created location ID")
    code: str = Field(description="Location code")
    path: str = Field(description="Materialized ltree path")
    parent_id: UUID | None = Field(description="Parent location ID")


class LocationUpdatedEvent(BaseModel):
    id: UUID = Field(description="Updated location ID")
    name: str = Field(description="Current location name")
    type: str = Field(description="Current location type")


class LocationMovedEvent(BaseModel):
    id: UUID = Field(description="Moved location ID")
    old_path: str = Field(description="Previous ltree path")
    new_path: str = Field(description="New ltree path")
    new_parent_id: UUID | None = Field(description="New parent location ID")


class LocationDeletedEvent(BaseModel):
    id: UUID = Field(description="Deleted location ID")
    code: str = Field(description="Location code")


class TeamCreatedEvent(BaseModel):
    id: UUID = Field(description="Created team ID")
    code: str = Field(description="Team code")
    name: str = Field(description="Team name")
    type: str = Field(description="Team type")


class TeamUpdatedEvent(BaseModel):
    id: UUID = Field(description="Updated team ID")
    name: str = Field(description="Current team name")
    type: str = Field(description="Current team type")


class TeamArchivedEvent(BaseModel):
    id: UUID = Field(description="Archived team ID")
    code: str = Field(description="Team code")


class TeamMemberAddedEvent(BaseModel):
    id: UUID = Field(description="Team membership record ID")
    team_id: UUID = Field(description="Team ID")
    member_id: UUID = Field(description="Member ID")
    team_role: str = Field(description="Assigned role: lead or member")


class TeamMemberUpdatedEvent(BaseModel):
    id: UUID = Field(description="Team membership record ID")
    team_id: UUID = Field(description="Team ID")
    member_id: UUID = Field(description="Member ID")
    team_role: str = Field(description="Current role: lead or member")


class TeamMemberRemovedEvent(BaseModel):
    team_id: UUID = Field(description="Team ID")
    member_id: UUID = Field(description="Removed member ID")
