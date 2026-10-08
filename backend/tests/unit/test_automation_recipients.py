# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Unit tests for recipient resolution, against a fake in-memory directory (§B6.3, M1.5-T2)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from app.core.permissions import ScopeType
from app.engines.automation.models import AutomationRule, RecipientRef
from app.engines.automation.recipients import resolve

HOLDER = uuid4()
ACTOR = uuid4()
TEAM_ID = uuid4()
TEAM_MEMBER_A = uuid4()
TEAM_MEMBER_B = uuid4()
ORG_UNIT_ID = uuid4()
ROLE_HOLDER = uuid4()
SUSPENDED = uuid4()


@dataclass
class FakeDirectory:
    """An in-memory `Directory`: no I/O, deterministic, built from whatever a test needs."""

    team_members: dict[UUID, set[UUID]] = field(default_factory=dict)
    role_grants: dict[tuple[str, ScopeType, UUID | None], set[UUID]] = field(default_factory=dict)
    active: set[UUID] = field(default_factory=set)

    async def team_member_ids(self, team_id: UUID) -> set[UUID]:
        return set(self.team_members.get(team_id, set()))

    async def members_with_role(
        self, role_key: str, scope_type: ScopeType, scope_id: UUID | None
    ) -> set[UUID]:
        return set(self.role_grants.get((role_key, scope_type, scope_id), set()))

    async def is_active(self, member_id: UUID) -> bool:
        return member_id in self.active


def _rule(*recipients: str, channels: tuple[str, ...] = ("inapp",)) -> AutomationRule:
    return AutomationRule.model_validate(
        {
            "when": "test.event",
            "then": {"recipients": list(recipients), "channels": list(channels), "template": "t"},
        }
    )


async def test_holder_is_resolved_from_the_holder_field() -> None:
    directory = FakeDirectory(active={HOLDER})
    rule = _rule("holder")
    data = {"member_id": str(HOLDER)}
    assert await resolve(data, rule, holder_field="member_id", directory=directory) == {HOLDER}


async def test_actor_is_resolved_from_actor_member_id_when_present() -> None:
    directory = FakeDirectory(active={ACTOR})
    rule = _rule("actor")
    data = {"actor_member_id": str(ACTOR)}
    assert await resolve(data, rule, holder_field=None, directory=directory) == {ACTOR}


async def test_actor_resolves_to_nothing_when_the_event_carries_no_actor() -> None:
    directory = FakeDirectory(active=set())
    rule = _rule("actor")
    assert await resolve({}, rule, holder_field=None, directory=directory) == set()


async def test_team_resolves_through_the_directory() -> None:
    directory = FakeDirectory(
        team_members={TEAM_ID: {TEAM_MEMBER_A, TEAM_MEMBER_B}}, active={TEAM_MEMBER_A, TEAM_MEMBER_B}
    )
    rule = _rule("team:team_id")
    data = {"team_id": str(TEAM_ID)}
    assert await resolve(data, rule, holder_field=None, directory=directory) == {TEAM_MEMBER_A, TEAM_MEMBER_B}


async def test_role_at_organization_scope() -> None:
    directory = FakeDirectory(
        role_grants={("asset_manager", ScopeType.ORGANIZATION, None): {ROLE_HOLDER}}, active={ROLE_HOLDER}
    )
    rule = _rule("role:asset_manager@organization")
    assert await resolve({}, rule, holder_field=None, directory=directory) == {ROLE_HOLDER}


async def test_role_at_org_unit_scope_reads_the_target_unit_from_the_event() -> None:
    directory = FakeDirectory(
        role_grants={("asset_manager", ScopeType.ORG_UNIT, ORG_UNIT_ID): {ROLE_HOLDER}}, active={ROLE_HOLDER}
    )
    rule = _rule("role:asset_manager@org_unit:owner_org_unit_id")
    data = {"owner_org_unit_id": str(ORG_UNIT_ID)}
    assert await resolve(data, rule, holder_field=None, directory=directory) == {ROLE_HOLDER}
    # The directory itself (PgDirectory) is what resolves "a grant at a parent org unit covers the
    # child" (§B5), through an ltree ancestor match - this fake just proves the resolver passes
    # the *target* unit id straight through, unchanged, to whatever the directory decides.


async def test_role_at_team_scope() -> None:
    directory = FakeDirectory(
        role_grants={("team_lead", ScopeType.TEAM, TEAM_ID): {ROLE_HOLDER}}, active={ROLE_HOLDER}
    )
    rule = _rule("role:team_lead@team:team_id")
    data = {"team_id": str(TEAM_ID)}
    assert await resolve(data, rule, holder_field=None, directory=directory) == {ROLE_HOLDER}


async def test_a_suspended_member_is_dropped() -> None:
    directory = FakeDirectory(active=set())  # SUSPENDED is never marked active
    rule = _rule("holder")
    data = {"member_id": str(SUSPENDED)}
    assert await resolve(data, rule, holder_field="member_id", directory=directory) == set()


async def test_the_same_member_resolved_twice_is_deduplicated() -> None:
    directory = FakeDirectory(
        role_grants={("asset_manager", ScopeType.ORGANIZATION, None): {HOLDER}}, active={HOLDER}
    )
    rule = _rule("holder", "role:asset_manager@organization")
    data = {"member_id": str(HOLDER)}
    assert await resolve(data, rule, holder_field="member_id", directory=directory) == {HOLDER}


@pytest.mark.parametrize("keyword", ["assignee", "requester", "team_lead", "org_unit_manager"])
def test_not_yet_available_keywords_are_rejected(keyword: str) -> None:
    with pytest.raises(ValidationError, match="not available yet"):
        _rule(keyword)


@pytest.mark.parametrize("raw", ["bogus", "role:asset_manager", "role:asset_manager@bogus", "team"])
def test_unknown_or_malformed_recipients_are_rejected(raw: str) -> None:
    with pytest.raises(ValidationError):
        _rule(raw)


@given(
    team_ids=st.sets(st.uuids(), min_size=0, max_size=5),
    active_fraction=st.sets(st.uuids(), min_size=0, max_size=5),
)
def test_resolved_set_is_always_a_subset_of_active_members_the_directory_knows(
    team_ids: set[UUID], active_fraction: set[UUID]
) -> None:
    # Hypothesis drives this test synchronously; it does not await a coroutine function, so the
    # resolve() call is run to completion through asyncio.run() inside a plain (non-async) test.
    async def _run() -> set[UUID]:
        team_id = uuid4()
        directory = FakeDirectory(team_members={team_id: team_ids}, active=active_fraction)
        rule = _rule("team:team_id")
        data = {"team_id": str(team_id)}
        return await resolve(data, rule, holder_field=None, directory=directory)

    resolved = asyncio.run(_run())
    assert resolved <= active_fraction
    assert resolved <= team_ids


def test_recipient_ref_parse_accepts_every_supported_form() -> None:
    assert RecipientRef.parse("holder").kind == "holder"
    assert RecipientRef.parse("actor").kind == "actor"
    team = RecipientRef.parse("team:team_id")
    assert team.kind == "team"
    assert team.team_field == "team_id"
    role = RecipientRef.parse("role:asset_manager@org_unit:owner_org_unit_id")
    assert role.kind == "role"
    assert role.role_key == "asset_manager"
    assert role.scope == "org_unit"
    assert role.scope_field == "owner_org_unit_id"
