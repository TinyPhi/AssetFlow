# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Organization structure and access error classes (§C1.5.1, §C4.5, M1.4-T4)."""

from __future__ import annotations

from typing import ClassVar

from app.core.problems import ConflictError, NotFoundError

__all__ = [
    "LocationConflictError",
    "LocationDeleteBlockedError",
    "LocationInvalidMoveError",
    "LocationNotFoundError",
    "LocationVersionConflictError",
    "OrgUnitArchiveBlockedError",
    "OrgUnitConflictError",
    "OrgUnitInvalidMoveError",
    "OrgUnitNotFoundError",
    "OrgUnitVersionConflictError",
    "TeamArchiveBlockedError",
    "TeamConflictError",
    "TeamMemberConflictError",
    "TeamMemberNotFoundError",
    "TeamNotFoundError",
    "TeamVersionConflictError",
]


class OrgUnitNotFoundError(NotFoundError):
    status_code = 404
    code: ClassVar[str] = "org_unit.not_found"
    title: ClassVar[str] = "Org unit not found"
    default_detail: ClassVar[str] = "The requested organizational unit does not exist."
    description: ClassVar[str] = "The requested organizational unit does not exist within caller scope."


class OrgUnitConflictError(ConflictError):
    status_code = 409
    code: ClassVar[str] = "org_unit.conflict"
    title: ClassVar[str] = "Org unit conflict"
    default_detail: ClassVar[str] = "An organizational unit with this code already exists."
    description: ClassVar[str] = "An organizational unit unique constraint was violated."


class OrgUnitVersionConflictError(ConflictError):
    status_code = 409
    code: ClassVar[str] = "org_unit.version_conflict"
    title: ClassVar[str] = "Org unit version conflict"
    default_detail: ClassVar[str] = "The organizational unit was modified by another request."
    description: ClassVar[str] = "The provided version does not match the current database version."


class OrgUnitInvalidMoveError(ConflictError):
    status_code = 409
    code: ClassVar[str] = "org_unit.invalid_move"
    title: ClassVar[str] = "Invalid org unit move"
    default_detail: ClassVar[str] = "Cannot move an organizational unit into itself or its own descendants."
    description: ClassVar[str] = "The requested move would create a cycle or cross organization boundaries."


class OrgUnitArchiveBlockedError(ConflictError):
    status_code = 409
    code: ClassVar[str] = "org_unit.archive_blocked"
    title: ClassVar[str] = "Org unit archive blocked"
    default_detail: ClassVar[str] = "Cannot archive an organizational unit with active children or members."
    description: ClassVar[str] = "Archiving is blocked by active child units, members, or teams."


class LocationNotFoundError(NotFoundError):
    status_code = 404
    code: ClassVar[str] = "location.not_found"
    title: ClassVar[str] = "Location not found"
    default_detail: ClassVar[str] = "The requested physical location does not exist."
    description: ClassVar[str] = "The requested physical location does not exist within caller scope."


class LocationConflictError(ConflictError):
    status_code = 409
    code: ClassVar[str] = "location.conflict"
    title: ClassVar[str] = "Location conflict"
    default_detail: ClassVar[str] = "A physical location with this code already exists."
    description: ClassVar[str] = "A physical location unique constraint was violated."


class LocationVersionConflictError(ConflictError):
    status_code = 409
    code: ClassVar[str] = "location.version_conflict"
    title: ClassVar[str] = "Location version conflict"
    default_detail: ClassVar[str] = "The physical location was modified by another request."
    description: ClassVar[str] = "The provided version does not match the current database version."


class LocationInvalidMoveError(ConflictError):
    status_code = 409
    code: ClassVar[str] = "location.invalid_move"
    title: ClassVar[str] = "Invalid location move"
    default_detail: ClassVar[str] = "Cannot move a physical location into itself or its own descendants."
    description: ClassVar[str] = "The requested move would create a cycle or cross organization boundaries."


class LocationDeleteBlockedError(ConflictError):
    status_code = 409
    code: ClassVar[str] = "location.delete_blocked"
    title: ClassVar[str] = "Location delete blocked"
    default_detail: ClassVar[str] = "Cannot delete a location with active sub-locations."
    description: ClassVar[str] = "Deletion is blocked by child locations or assigned resources."


class TeamNotFoundError(NotFoundError):
    status_code = 404
    code: ClassVar[str] = "team.not_found"
    title: ClassVar[str] = "Team not found"
    default_detail: ClassVar[str] = "The requested team does not exist."
    description: ClassVar[str] = "The requested team does not exist within caller scope."


class TeamConflictError(ConflictError):
    status_code = 409
    code: ClassVar[str] = "team.conflict"
    title: ClassVar[str] = "Team conflict"
    default_detail: ClassVar[str] = "A team with this code already exists."
    description: ClassVar[str] = "A team unique constraint was violated."


class TeamVersionConflictError(ConflictError):
    status_code = 409
    code: ClassVar[str] = "team.version_conflict"
    title: ClassVar[str] = "Team version conflict"
    default_detail: ClassVar[str] = "The team was modified by another request."
    description: ClassVar[str] = "The provided version does not match the current database version."


class TeamArchiveBlockedError(ConflictError):
    status_code = 409
    code: ClassVar[str] = "team.archive_blocked"
    title: ClassVar[str] = "Team archive blocked"
    default_detail: ClassVar[str] = "Cannot archive a team with active members."
    description: ClassVar[str] = "Archiving is blocked by active team members or open work orders."


class TeamMemberNotFoundError(NotFoundError):
    status_code = 404
    code: ClassVar[str] = "team_member.not_found"
    title: ClassVar[str] = "Team member not found"
    default_detail: ClassVar[str] = "The member is not assigned to this team."
    description: ClassVar[str] = "The requested team membership record does not exist."


class TeamMemberConflictError(ConflictError):
    status_code = 409
    code: ClassVar[str] = "team_member.conflict"
    title: ClassVar[str] = "Team member conflict"
    default_detail: ClassVar[str] = "The member is already assigned to this team."
    description: ClassVar[str] = "The member already has an active assignment in this team."
