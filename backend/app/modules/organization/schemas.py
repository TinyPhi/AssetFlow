# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Organization structure and access Pydantic schemas (§B5.2, §C1.3, §C4.1, M1.4-T4)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "LocationCreate",
    "LocationMove",
    "LocationRead",
    "LocationUpdate",
    "OrgUnitArchive",
    "OrgUnitCreate",
    "OrgUnitMove",
    "OrgUnitRead",
    "OrgUnitUpdate",
    "TeamArchive",
    "TeamCreate",
    "TeamMemberAdd",
    "TeamMemberRead",
    "TeamMemberUpdate",
    "TeamRead",
    "TeamUpdate",
]

_CODE_RE = re.compile(r"^[a-z0-9_]+(-[a-z0-9_]+)*$", re.IGNORECASE)


def validate_code(val: str) -> str:
    cleaned = val.strip().lower()
    if not cleaned:
        raise ValueError("Code cannot be empty")
    if len(cleaned) > 64:
        raise ValueError("Code cannot exceed 64 characters")
    if not _CODE_RE.match(cleaned):
        raise ValueError("Code must contain only alphanumeric characters, underscores, and hyphens")
    return cleaned


# ==============================================================================
# Organizational Units
# ==============================================================================


class OrgUnitCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(description="Unique business code for the organizational unit")
    name: str = Field(min_length=1, max_length=255, description="Display name of the organizational unit")
    type: str = Field(min_length=1, max_length=64, description="Unit type, e.g. division, unit, branch")
    parent_id: UUID | None = Field(default=None, description="Parent unit ID (None if root)")
    manager_member_id: UUID | None = Field(default=None, description="Appointed manager member ID")

    @field_validator("code")
    @classmethod
    def _validate_code(cls, v: str) -> str:
        return validate_code(v)


class OrgUnitUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255, description="Updated display name")
    type: str | None = Field(default=None, min_length=1, max_length=64, description="Updated unit type")
    manager_member_id: UUID | None = Field(default=None, description="Updated manager member ID")
    clear_manager: bool = Field(default=False, description="Explicitly remove the current manager")
    version: int = Field(ge=1, description="Current record version for optimistic concurrency control")


class OrgUnitMove(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_parent_id: UUID = Field(description="Destination parent organizational unit ID")
    version: int = Field(ge=1, description="Current record version for optimistic concurrency control")


class OrgUnitArchive(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1, description="Current record version for optimistic concurrency control")


class OrgUnitRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="Organizational unit unique ID")
    organization_id: UUID = Field(description="Tenant organization ID")
    parent_id: UUID | None = Field(description="Parent organizational unit ID")
    path: str = Field(description="Ltree materialized path in the hierarchy")
    type: str = Field(description="Organizational unit type")
    code: str = Field(description="Business code")
    name: str = Field(description="Display name")
    manager_member_id: UUID | None = Field(description="Manager member ID")
    status: str = Field(description="Unit status: active or archived")
    version: int = Field(description="Optimistic concurrency version")
    created_at: datetime = Field(description="Timestamp of creation")
    updated_at: datetime = Field(description="Timestamp of last update")


# ==============================================================================
# Locations
# ==============================================================================


class LocationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(description="Unique business code for the physical location")
    name: str = Field(min_length=1, max_length=255, description="Display name of the location")
    type: str = Field(
        min_length=1, max_length=64, description="Location type, e.g. site, building, floor, room"
    )
    parent_id: UUID | None = Field(default=None, description="Parent location ID (None if top-level site)")
    address: dict[str, Any] = Field(default_factory=dict, description="Structured address metadata")

    @field_validator("code")
    @classmethod
    def _validate_code(cls, v: str) -> str:
        return validate_code(v)


class LocationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255, description="Updated display name")
    type: str | None = Field(default=None, min_length=1, max_length=64, description="Updated location type")
    address: dict[str, Any] | None = Field(default=None, description="Updated address metadata")
    version: int = Field(ge=1, description="Current record version for optimistic concurrency control")


class LocationMove(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_parent_id: UUID | None = Field(
        default=None, description="Destination parent location ID (or None for top-level)"
    )
    version: int = Field(ge=1, description="Current record version for optimistic concurrency control")


class LocationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="Location unique ID")
    organization_id: UUID = Field(description="Tenant organization ID")
    parent_id: UUID | None = Field(description="Parent location ID")
    path: str = Field(description="Ltree materialized path in the hierarchy")
    type: str = Field(description="Location type")
    code: str = Field(description="Business code")
    name: str = Field(description="Display name")
    address: dict[str, Any] = Field(description="Address metadata")
    version: int = Field(description="Optimistic concurrency version")
    created_at: datetime = Field(description="Timestamp of creation")
    updated_at: datetime = Field(description="Timestamp of last update")


# ==============================================================================
# Teams
# ==============================================================================


class TeamCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(description="Unique business code for the team")
    name: str = Field(min_length=1, max_length=255, description="Display name of the team")
    type: str = Field(
        min_length=1, max_length=64, description="Team type, e.g. maintenance, crew, operations"
    )
    owning_org_unit_id: UUID | None = Field(
        default=None, description="Associated owning organizational unit ID"
    )
    skills: list[str] = Field(
        default_factory=list, description="Skill tags required/associated with the team"
    )
    working_calendar_id: UUID | None = Field(default=None, description="Assigned working calendar ID")

    @field_validator("code")
    @classmethod
    def _validate_code(cls, v: str) -> str:
        return validate_code(v)


class TeamUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255, description="Updated display name")
    type: str | None = Field(default=None, min_length=1, max_length=64, description="Updated team type")
    owning_org_unit_id: UUID | None = Field(default=None, description="Updated owning organizational unit ID")
    clear_owning_org_unit: bool = Field(default=False, description="Remove the owning org unit association")
    skills: list[str] | None = Field(default=None, description="Updated skill tags")
    working_calendar_id: UUID | None = Field(default=None, description="Updated working calendar ID")
    clear_working_calendar: bool = Field(default=False, description="Remove the working calendar association")
    version: int = Field(ge=1, description="Current record version for optimistic concurrency control")


class TeamArchive(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1, description="Current record version for optimistic concurrency control")


class TeamRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="Team unique ID")
    organization_id: UUID = Field(description="Tenant organization ID")
    code: str = Field(description="Business code")
    name: str = Field(description="Display name")
    owning_org_unit_id: UUID | None = Field(description="Owning organizational unit ID")
    type: str = Field(description="Team type")
    skills: list[str] = Field(description="Skill tags")
    working_calendar_id: UUID | None = Field(description="Working calendar ID")
    status: str = Field(description="Team status: active or archived")
    version: int = Field(description="Optimistic concurrency version")
    created_at: datetime = Field(description="Timestamp of creation")
    updated_at: datetime = Field(description="Timestamp of last update")


# ==============================================================================
# Team Members
# ==============================================================================


class TeamMemberAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    member_id: UUID = Field(description="Member ID to assign to the team")
    team_role: str = Field(default="member", description="Role in team: lead or member")
    valid_from: datetime | None = Field(default=None, description="Assignment effective start date")
    valid_to: datetime | None = Field(default=None, description="Assignment effective expiration date")

    @field_validator("team_role")
    @classmethod
    def _validate_role(cls, v: str) -> str:
        role = v.strip().lower()
        if role not in ("lead", "member"):
            raise ValueError("team_role must be 'lead' or 'member'")
        return role


class TeamMemberUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_role: str | None = Field(default=None, description="Updated role in team: lead or member")
    valid_to: datetime | None = Field(default=None, description="Updated expiration timestamp")

    @field_validator("team_role")
    @classmethod
    def _validate_role(cls, v: str | None) -> str | None:
        if v is None:
            return None
        role = v.strip().lower()
        if role not in ("lead", "member"):
            raise ValueError("team_role must be 'lead' or 'member'")
        return role


class TeamMemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="Team membership assignment unique ID")
    organization_id: UUID = Field(description="Tenant organization ID")
    team_id: UUID = Field(description="Team ID")
    member_id: UUID = Field(description="Member ID")
    team_role: str = Field(description="Role in team: lead or member")
    valid_from: datetime = Field(description="Assignment effective start date")
    valid_to: datetime | None = Field(description="Assignment effective expiration date")
    created_at: datetime = Field(description="Timestamp of creation")
    updated_at: datetime = Field(description="Timestamp of last update")
