# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Property tests for the scope resolver and UUIDv7 ids (AF-006, AF-020)."""

from __future__ import annotations

from itertools import pairwise
from uuid import UUID

from hypothesis import given
from hypothesis import strategies as st

from app.core.ids import uuid7, uuid7_str
from app.core.permissions import ScopeType
from app.core.scope import MemberContext, RoleGrant, ScopeResolver

_TEAMS = st.sampled_from(["team-a", "team-b", "team-c", "team-d"])
_PERMISSION = "work_order.read"


def _team_grant(team: str) -> RoleGrant:
    return RoleGrant(
        id=f"g-{team}",
        organization_id="org-1",
        role_key="technician",
        scope_type=ScopeType.TEAM,
        scope_id=team,
    )


def test_member_of_team_without_grant_cannot_list_or_read_that_team() -> None:
    resolver = ScopeResolver()
    member = MemberContext(
        member_id="m-1",
        organization_id="org-1",
        grants=(_team_grant("team-a"),),
        team_ids=("team-a", "team-b"),
    )
    flt = resolver.resolve_scope_filter(member, _PERMISSION)
    assert flt.team_ids == ("team-a",)
    assert resolver.check_access(member, _PERMISSION, {"team_id": "team-a"})
    assert not resolver.check_access(member, _PERMISSION, {"team_id": "team-b"})


@given(granted=st.sets(_TEAMS), memberships=st.sets(_TEAMS), target=_TEAMS)
def test_team_scope_covers_exactly_granted_teams(
    granted: set[str], memberships: set[str], target: str
) -> None:
    resolver = ScopeResolver()
    member = MemberContext(
        member_id="m-1",
        organization_id="org-1",
        grants=tuple(_team_grant(t) for t in sorted(granted)),
        team_ids=tuple(sorted(memberships)),
    )
    flt = resolver.resolve_scope_filter(member, _PERMISSION)
    assert set(flt.team_ids) == granted
    assert resolver.check_access(member, _PERMISSION, {"team_id": target}) == (target in granted)
    assert flt.covers(team_id=target) == (target in granted)


@given(st.lists(st.integers(min_value=0, max_value=10)))
def test_uuid7_is_valid_and_strictly_increasing(sizes: list[int]) -> None:
    values = [uuid7() for _ in range(sum(sizes) + 2)]
    for u in values:
        assert u.version == 7
        assert u.variant == "specified in RFC 4122"
    assert all(a < b for a, b in pairwise(values))
    assert UUID(uuid7_str()).version == 7
