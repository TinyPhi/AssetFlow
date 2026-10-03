# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""`can_grant`: nobody grants more than they hold, pure logic, no database (M1.4-T5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.permissions import ScopeType
from app.core.scope import MemberContext, RoleGrant
from app.modules.organization.grants import can_grant


def _grant(
    role_key: str, scope_type: ScopeType, scope_id: str | None = None, org_unit_path: str | None = None
) -> RoleGrant:
    return RoleGrant(
        id="g",
        organization_id="org",
        role_key=role_key,
        scope_type=scope_type,
        scope_id=scope_id,
        org_unit_path=org_unit_path,
    )


def test_org_admin_can_grant_any_role_anywhere() -> None:
    admin = MemberContext(
        member_id="m", organization_id="org", grants=(_grant("admin", ScopeType.ORGANIZATION),)
    )
    assert can_grant(admin, role_key="admin", scope_type=ScopeType.ORGANIZATION) is True
    assert (
        can_grant(
            admin,
            role_key="technician",
            scope_type=ScopeType.ORG_UNIT,
            scope_id="u1",
            org_unit_path="root.hq",
        )
        is True
    )
    assert can_grant(admin, role_key="team_lead", scope_type=ScopeType.TEAM, scope_id="t1") is True


def test_technician_cannot_grant_admin() -> None:
    """A narrow role cannot grant a role that carries permissions it does not itself hold."""
    technician = MemberContext(
        member_id="m", organization_id="org", grants=(_grant("technician", ScopeType.ORGANIZATION),)
    )
    assert can_grant(technician, role_key="admin", scope_type=ScopeType.ORGANIZATION) is False


def test_org_unit_scoped_admin_can_grant_within_its_own_subtree_only() -> None:
    hq_admin = MemberContext(
        member_id="m",
        organization_id="org",
        grants=(_grant("admin", ScopeType.ORG_UNIT, scope_id="hq", org_unit_path="root.hq"),),
    )
    # same unit
    assert (
        can_grant(
            hq_admin,
            role_key="technician",
            scope_type=ScopeType.ORG_UNIT,
            scope_id="hq",
            org_unit_path="root.hq",
        )
        is True
    )
    # a descendant of its own subtree
    assert (
        can_grant(
            hq_admin,
            role_key="technician",
            scope_type=ScopeType.ORG_UNIT,
            scope_id="svc",
            org_unit_path="root.hq.service",
        )
        is True
    )
    # a sibling subtree is out of scope
    assert (
        can_grant(
            hq_admin,
            role_key="technician",
            scope_type=ScopeType.ORG_UNIT,
            scope_id="ops",
            org_unit_path="root.ops",
        )
        is False
    )
    # organization-wide scope is wider than the granter's own org_unit scope
    assert can_grant(hq_admin, role_key="technician", scope_type=ScopeType.ORGANIZATION) is False


def test_team_scoped_grant_only_covers_its_own_team() -> None:
    team_lead = MemberContext(
        member_id="m", organization_id="org", grants=(_grant("team_lead", ScopeType.TEAM, scope_id="team-a"),)
    )
    assert can_grant(team_lead, role_key="technician", scope_type=ScopeType.TEAM, scope_id="team-a") is True
    assert can_grant(team_lead, role_key="technician", scope_type=ScopeType.TEAM, scope_id="team-b") is False
    assert can_grant(team_lead, role_key="technician", scope_type=ScopeType.ORG_UNIT, scope_id="x") is False


def test_suspended_granter_can_grant_nothing() -> None:
    suspended_admin = MemberContext(
        member_id="m",
        organization_id="org",
        is_suspended=True,
        grants=(_grant("admin", ScopeType.ORGANIZATION),),
    )
    assert can_grant(suspended_admin, role_key="technician", scope_type=ScopeType.ORGANIZATION) is False


def test_unknown_role_key_is_refused() -> None:
    admin = MemberContext(
        member_id="m", organization_id="org", grants=(_grant("admin", ScopeType.ORGANIZATION),)
    )
    assert can_grant(admin, role_key="not-a-real-role", scope_type=ScopeType.ORGANIZATION) is False


def test_expired_grant_does_not_cover_anything() -> None:
    expired = RoleGrant(
        id="g",
        organization_id="org",
        role_key="admin",
        scope_type=ScopeType.ORGANIZATION,
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    member = MemberContext(member_id="m", organization_id="org", grants=(expired,))
    assert can_grant(member, role_key="technician", scope_type=ScopeType.ORGANIZATION) is False
