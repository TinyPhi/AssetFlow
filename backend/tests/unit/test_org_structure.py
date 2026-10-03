# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Unit tests for organization structure schemas, ltree labeling, and errors (§M1.4-T4)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.organization.errors import (
    LocationConflictError,
    LocationDeleteBlockedError,
    LocationInvalidMoveError,
    LocationNotFoundError,
    LocationVersionConflictError,
    OrgUnitArchiveBlockedError,
    OrgUnitConflictError,
    OrgUnitInvalidMoveError,
    OrgUnitNotFoundError,
    OrgUnitVersionConflictError,
    TeamArchiveBlockedError,
    TeamConflictError,
    TeamMemberConflictError,
    TeamMemberNotFoundError,
    TeamNotFoundError,
    TeamVersionConflictError,
)
from app.modules.organization.repository import to_ltree_label
from app.modules.organization.schemas import (
    LocationCreate,
    LocationMove,
    LocationUpdate,
    OrgUnitArchive,
    OrgUnitCreate,
    OrgUnitMove,
    TeamArchive,
    TeamCreate,
    TeamMemberAdd,
    TeamMemberUpdate,
    TeamUpdate,
)


def test_to_ltree_label() -> None:
    assert to_ltree_label("HQ") == "hq"
    assert to_ltree_label("north-east") == "north_east"
    assert to_ltree_label("Depot-101") == "depot_101"
    assert to_ltree_label("valid_label_123") == "valid_label_123"
    assert to_ltree_label("123abc") == "123abc"
    with pytest.raises(ValueError, match="empty ltree label"):
        to_ltree_label("")


def test_org_unit_schemas() -> None:
    # Valid OrgUnitCreate - code is normalized to lowercase
    create_dto = OrgUnitCreate(code="ENG", name="Engineering", type="department")
    assert create_dto.code == "eng"
    assert create_dto.name == "Engineering"

    with pytest.raises(ValidationError):
        OrgUnitCreate(code="", name="Engineering", type="department")

    with pytest.raises(ValidationError):
        OrgUnitCreate(code="ENG", name="", type="department")

    # Valid OrgUnitMove
    move_dto = OrgUnitMove(new_parent_id=uuid4(), version=1)
    assert move_dto.version == 1

    with pytest.raises(ValidationError):
        OrgUnitMove(new_parent_id=None, version=0)

    # Valid OrgUnitArchive
    archive_dto = OrgUnitArchive(version=2)
    assert archive_dto.version == 2


def test_location_schemas() -> None:
    loc_create = LocationCreate(code="SITE-1", name="Main Plant", type="plant", address={"city": "Austin"})
    assert loc_create.code == "site-1"
    assert loc_create.address == {"city": "Austin"}

    loc_update = LocationUpdate(name="Main Plant North", version=1)
    assert loc_update.name == "Main Plant North"
    assert loc_update.version == 1

    loc_move = LocationMove(new_parent_id=uuid4(), version=3)
    assert loc_move.version == 3


def test_team_schemas() -> None:
    team_create = TeamCreate(
        code="TEAM-A", name="Alpha Team", type="maintenance", skills=["electrical", "hvac"]
    )
    assert team_create.code == "team-a"
    assert team_create.skills == ["electrical", "hvac"]

    team_update = TeamUpdate(name="Alpha Strike", version=2)
    assert team_update.name == "Alpha Strike"

    team_archive = TeamArchive(version=2)
    assert team_archive.version == 2

    member_add = TeamMemberAdd(member_id=uuid4(), team_role="lead")
    assert member_add.team_role == "lead"

    with pytest.raises(ValidationError):
        TeamMemberAdd(member_id=uuid4(), team_role="invalid")

    member_update = TeamMemberUpdate(team_role="member")
    assert member_update.team_role == "member"


def test_error_classes() -> None:
    e1 = OrgUnitNotFoundError()
    assert e1.status_code == 404
    assert e1.code == "org_unit.not_found"

    e2 = OrgUnitArchiveBlockedError("Cannot archive unit with 2 active children (blocker: active_children)")
    assert e2.status_code == 409
    assert e2.code == "org_unit.archive_blocked"
    assert "active_children" in e2.detail

    e3 = OrgUnitInvalidMoveError("Cannot move unit into its own descendant")
    assert e3.status_code == 409
    assert e3.code == "org_unit.invalid_move"

    e4 = OrgUnitConflictError("Code exists")
    assert e4.status_code == 409
    assert e4.code == "org_unit.conflict"

    e5 = OrgUnitVersionConflictError()
    assert e5.status_code == 409
    assert e5.code == "org_unit.version_conflict"

    e6 = LocationNotFoundError()
    assert e6.status_code == 404
    assert e6.code == "location.not_found"

    e7 = LocationConflictError("Location code exists")
    assert e7.status_code == 409
    assert e7.code == "location.conflict"

    e8 = LocationDeleteBlockedError("Cannot delete location with children")
    assert e8.status_code == 409
    assert e8.code == "location.delete_blocked"

    e9 = LocationInvalidMoveError()
    assert e9.status_code == 409
    assert e9.code == "location.invalid_move"

    e10 = LocationVersionConflictError()
    assert e10.status_code == 409
    assert e10.code == "location.version_conflict"

    e11 = TeamNotFoundError()
    assert e11.status_code == 404
    assert e11.code == "team.not_found"

    e12 = TeamConflictError("Team code exists")
    assert e12.status_code == 409
    assert e12.code == "team.conflict"

    e13 = TeamArchiveBlockedError("Active members")
    assert e13.status_code == 409
    assert e13.code == "team.archive_blocked"

    e14 = TeamVersionConflictError()
    assert e14.status_code == 409
    assert e14.code == "team.version_conflict"

    e15 = TeamMemberNotFoundError()
    assert e15.status_code == 404
    assert e15.code == "team_member.not_found"

    e16 = TeamMemberConflictError()
    assert e16.status_code == 409
    assert e16.code == "team_member.conflict"
