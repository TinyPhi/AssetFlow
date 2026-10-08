# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The planner's preference filter (§B6.3 rule 7): default on, off cells dropped, mandatory in-app kept."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.engines.automation.planner import NotificationIntent, filter_by_preferences

ORG = uuid4()
ADA, BOB = uuid4(), uuid4()
EVENT = "team_member.added"


class _Off:
    """A `Preferences` that reports a fixed set of switched-off cells."""

    def __init__(self, *cells: tuple[UUID, str, str]) -> None:
        self.cells = set(cells)
        self.asked: list[tuple[set[UUID], set[str]]] = []

    async def disabled(self, member_ids: set[UUID], event_types: set[str]) -> set[tuple[UUID, str, str]]:
        self.asked.append((member_ids, event_types))
        return self.cells


def _intent(member: UUID, channel: str, *, mandatory: bool = False, event: str = EVENT) -> NotificationIntent:
    return NotificationIntent(
        event_id=uuid4(),
        organization_id=ORG,
        member_id=member,
        channel_key=channel,
        template_key="team-member-added",
        idempotency_key=f"{member}-{channel}-{event}",
        event_type=event,
        event_data={},
        mandatory=mandatory,
    )


def _keys(intents: list[NotificationIntent]) -> list[tuple[UUID, str]]:
    return [(i.member_id, i.channel_key) for i in intents]


@pytest.mark.parametrize(
    ("off", "mandatory", "expected"),
    [
        pytest.param([], False, [(ADA, "inapp"), (ADA, "email"), (BOB, "inapp")], id="default-is-on"),
        pytest.param(
            [(ADA, EVENT, "email")], False, [(ADA, "inapp"), (BOB, "inapp")], id="email-off-is-dropped"
        ),
        pytest.param(
            [(ADA, EVENT, "inapp")], False, [(ADA, "email"), (BOB, "inapp")], id="inapp-off-is-dropped"
        ),
        pytest.param(
            [(ADA, EVENT, "inapp")],
            True,
            [(ADA, "inapp"), (ADA, "email"), (BOB, "inapp")],
            id="mandatory-inapp-kept",
        ),
        pytest.param(
            [(ADA, EVENT, "email")], True, [(ADA, "inapp"), (BOB, "inapp")], id="mandatory-never-keeps-email"
        ),
        pytest.param([(BOB, EVENT, "inapp")], False, [(ADA, "inapp"), (ADA, "email")], id="only-that-member"),
        pytest.param(
            [(ADA, "other.event", "email")],
            False,
            [(ADA, "inapp"), (ADA, "email"), (BOB, "inapp")],
            id="other-event",
        ),
    ],
)
async def test_the_filter_applies_switched_off_cells(
    off: list[tuple[UUID, str, str]], mandatory: bool, expected: list[tuple[UUID, str]]
) -> None:
    intents = [
        _intent(ADA, "inapp", mandatory=mandatory),
        _intent(ADA, "email", mandatory=mandatory),
        _intent(BOB, "inapp", mandatory=mandatory),
    ]
    assert _keys(await filter_by_preferences(intents, _Off(*off))) == expected


async def test_a_stale_row_that_says_off_cannot_drop_a_mandatory_inapp_notice() -> None:
    stale = _Off((ADA, EVENT, "inapp"))
    kept = await filter_by_preferences([_intent(ADA, "inapp", mandatory=True)], stale)
    assert _keys(kept) == [(ADA, "inapp")]


async def test_without_a_preference_source_everything_passes() -> None:
    intents = [_intent(ADA, "inapp"), _intent(ADA, "email")]
    assert await filter_by_preferences(intents, None) == intents


async def test_nothing_is_read_when_there_is_nothing_to_filter() -> None:
    source = _Off()
    assert await filter_by_preferences([], source) == []
    assert source.asked == []


async def test_one_read_covers_the_whole_batch() -> None:
    source = _Off()
    intents = [_intent(ADA, "inapp"), _intent(BOB, "email"), _intent(BOB, "inapp", event="team.created")]
    await filter_by_preferences(intents, source)
    assert source.asked == [({ADA, BOB}, {EVENT, "team.created"})]
