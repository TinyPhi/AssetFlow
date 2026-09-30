# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Unit tests for permissions and scope resolution (§B5.3, M1.3-T5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.permissions import (
    ScopeFilter,
    ScopeType,
    matches_permission,
    validate_permission_pattern,
)
from app.core.problems import PermissionDeniedError
from app.core.scope import MemberContext, RoleGrant, ScopeResolver


def test_permission_pattern_validation() -> None:
    assert validate_permission_pattern("asset.read")
    assert validate_permission_pattern("work_order.dispatch")
    assert validate_permission_pattern("work_order.*")
    assert validate_permission_pattern("platform.organization_create")
    assert not validate_permission_pattern("invalid")
    assert not validate_permission_pattern("asset.read.extra")
    assert not validate_permission_pattern("*.read")


def test_matches_permission() -> None:
    assert matches_permission("asset.read", "asset.read")
    assert not matches_permission("asset.read", "asset.write")
    assert matches_permission("asset.*", "asset.read")
    assert matches_permission("asset.*", "asset.assign")
    assert not matches_permission("asset.*", "work_order.read")
    # Organization wildcard matches all except platform
    assert matches_permission("*", "asset.read")
    assert matches_permission("*", "work_order.dispatch")
    assert not matches_permission("*", "platform.admin")


def test_scope_filter_organization() -> None:
    flt = ScopeFilter.all_organization()
    assert not flt.is_empty
    assert flt.organization
    assert flt.covers(owner_org_unit_path="depot.north", team_id="team-1", holder_id="user-1")


def test_scope_filter_granular() -> None:
    flt = ScopeFilter(
        organization=False,
        org_unit_paths=("ops.north",),
        team_ids=("team-alpha",),
        member_id="member-123",
    )
    assert not flt.is_empty
    # Matches org unit and sub-unit
    assert flt.covers(owner_org_unit_path="ops.north")
    assert flt.covers(owner_org_unit_path="ops.north.depot7")
    assert not flt.covers(owner_org_unit_path="ops.south")

    # Matches team
    assert flt.covers(team_id="team-alpha")
    assert not flt.covers(team_id="team-beta")

    # Matches self
    assert flt.covers(holder_id="member-123")
    assert flt.covers(assignee_id="member-123")
    assert not flt.covers(holder_id="member-999")


def test_scope_resolver_grants() -> None:
    resolver = ScopeResolver()
    grant_org = RoleGrant(
        id="g-1",
        organization_id="org-1",
        role_key="asset_manager",
        scope_type=ScopeType.ORGANIZATION,
    )
    member = MemberContext(
        member_id="m-1",
        organization_id="org-1",
        is_suspended=False,
        grants=(grant_org,),
    )

    assert resolver.has_permission(member, "asset.read")
    assert resolver.has_permission(member, "asset.assign")
    assert not resolver.has_permission(member, "work_order.dispatch")

    # Access check on any resource
    assert resolver.check_access(member, "asset.read", {"owner_org_unit_path": "any.path"})

    # Scope filter should be all-organization
    flt = resolver.resolve_scope_filter(member, "asset.read")
    assert flt.organization


def test_scope_resolver_org_unit_and_sub_unit() -> None:
    resolver = ScopeResolver()
    grant_unit = RoleGrant(
        id="g-2",
        organization_id="org-1",
        role_key="technician",
        scope_type=ScopeType.ORG_UNIT,
        org_unit_path="ops.west",
    )
    member = MemberContext(
        member_id="m-2",
        organization_id="org-1",
        grants=(grant_unit,),
        team_ids=("crew-1",),
    )

    assert resolver.has_permission(member, "work_order.read")
    # Resource in ops.west
    assert resolver.check_access(member, "work_order.read", {"owner_org_unit_path": "ops.west"})
    # Resource in ops.west.sub
    assert resolver.check_access(member, "work_order.read", {"owner_org_unit_path": "ops.west.sub"})
    # Resource outside ops.west
    assert not resolver.check_access(member, "work_order.read", {"owner_org_unit_path": "ops.east"})

    # Require raises PermissionDeniedError
    with pytest.raises(PermissionDeniedError):
        resolver.require(member, "work_order.read", {"owner_org_unit_path": "ops.east"})


def test_scope_resolver_self_scope() -> None:
    resolver = ScopeResolver()
    grant_self = RoleGrant(
        id="g-3",
        organization_id="org-1",
        role_key="member",
        scope_type=ScopeType.SELF,
    )
    member = MemberContext(
        member_id="m-3",
        organization_id="org-1",
        grants=(grant_self,),
    )

    assert resolver.has_permission(member, "asset.acknowledge")
    # Covers held asset
    assert resolver.check_access(member, "asset.acknowledge", {"holder_member_id": "m-3"})
    # Does not cover another member's asset
    assert not resolver.check_access(member, "asset.acknowledge", {"holder_member_id": "m-4"})

    flt = resolver.resolve_scope_filter(member, "asset.acknowledge")
    assert flt.member_id == "m-3"
    assert not flt.organization


def test_scope_resolver_expired_grant() -> None:
    resolver = ScopeResolver()
    expired_time = datetime.now(UTC) - timedelta(minutes=10)
    grant_expired = RoleGrant(
        id="g-exp",
        organization_id="org-1",
        role_key="admin",
        scope_type=ScopeType.ORGANIZATION,
        expires_at=expired_time,
    )
    member = MemberContext(
        member_id="m-exp",
        organization_id="org-1",
        grants=(grant_expired,),
    )

    assert not resolver.has_permission(member, "asset.read")


def test_scope_resolver_suspended_member() -> None:
    resolver = ScopeResolver()
    grant = RoleGrant(
        id="g-adm",
        organization_id="org-1",
        role_key="admin",
        scope_type=ScopeType.ORGANIZATION,
    )
    member = MemberContext(
        member_id="m-susp",
        organization_id="org-1",
        is_suspended=True,
        grants=(grant,),
    )

    assert not resolver.has_permission(member, "asset.read")
    assert not resolver.check_access(member, "asset.read")
    assert resolver.resolve_scope_filter(member, "asset.read").is_empty
