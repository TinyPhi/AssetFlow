# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Pure asset-tag formatting and shape validation (master M2.1-T3, §B7.3, §B8.1).

`validate_supplied_tag`'s format check is pure; its uniqueness half needs one `fetchval`, stubbed
here with an in-memory fake so these stay unit tests (no database, network or file system, per
`testing.md`). The real per-organization sequence, uniqueness and concurrency proof against a real
PostgreSQL is `tests/integration/test_asset_tag_sequence.py`.
"""

from __future__ import annotations

import uuid
from typing import cast

import pytest

from app.core.db import Connection
from app.modules.assets.config import TagConfig
from app.modules.assets.errors import TagConflictError, TagInvalidError
from app.modules.assets.tags import _tag_pattern, effective_prefix, format_tag, validate_supplied_tag

_TAG = TagConfig(prefix="AST", separator="-", digits=5)
_ORG = uuid.uuid4()


class _FakeConn:
    """Stands in for `app.core.db.Connection`: only `fetchval` is used by `validate_supplied_tag`."""

    def __init__(self, *, conflict: bool) -> None:
        self._conflict = conflict
        self.calls: list[tuple[object, ...]] = []

    async def fetchval(self, query: str, *args: object) -> int | None:
        self.calls.append((query, *args))
        return 1 if self._conflict else None


def _conn(*, conflict: bool) -> tuple[Connection, _FakeConn]:
    """A fake connection, as the real `Connection` type at the call boundary and as itself to assert on."""
    fake = _FakeConn(conflict=conflict)
    return cast("Connection", fake), fake


def test_format_tag_pads_to_the_configured_digit_count() -> None:
    assert format_tag(_TAG, None, 1) == "AST-00001"
    assert format_tag(_TAG, None, 42) == "AST-00042"


def test_format_tag_uses_the_template_prefix_when_no_category_override() -> None:
    assert effective_prefix(_TAG, None) == "AST"
    assert format_tag(_TAG, None, 7) == "AST-00007"


def test_format_tag_uses_the_category_prefix_override_when_set() -> None:
    assert effective_prefix(_TAG, "LAP") == "LAP"
    assert format_tag(_TAG, "LAP", 7) == "LAP-00007"


def test_format_tag_overflow_keeps_every_digit_instead_of_wrapping() -> None:
    assert format_tag(_TAG, None, 100_000) == "AST-100000"
    assert format_tag(_TAG, None, 123_456_789) == "AST-123456789"


def test_format_tag_with_no_separator() -> None:
    no_sep = TagConfig(prefix="FAC", separator="", digits=4)
    assert format_tag(no_sep, None, 3) == "FAC0003"


@pytest.mark.parametrize(
    ("category_prefix", "number", "expected"),
    [
        (None, 1, "AST-00001"),
        ("LAP", 100_000, "LAP-100000"),
    ],
)
def test_format_tag_round_trips_through_its_own_pattern(
    category_prefix: str | None, number: int, expected: str
) -> None:
    tag = format_tag(_TAG, category_prefix, number)
    assert tag == expected
    assert _tag_pattern(_TAG, category_prefix).match(tag)


async def test_validate_supplied_tag_accepts_a_well_formed_unused_tag() -> None:
    conn, fake = _conn(conflict=False)
    await validate_supplied_tag(conn, _ORG, _TAG, None, "AST-00042")
    assert fake.calls  # the uniqueness check did run


async def test_validate_supplied_tag_refuses_a_clash() -> None:
    conn, _fake = _conn(conflict=True)
    with pytest.raises(TagConflictError):
        await validate_supplied_tag(conn, _ORG, _TAG, None, "AST-00042")


async def test_validate_supplied_tag_refuses_wrong_prefix() -> None:
    conn, fake = _conn(conflict=False)
    with pytest.raises(TagInvalidError):
        await validate_supplied_tag(conn, _ORG, _TAG, None, "XXX-00042")
    assert not fake.calls  # format is checked before any database round trip


async def test_validate_supplied_tag_refuses_wrong_separator() -> None:
    conn, _fake = _conn(conflict=False)
    with pytest.raises(TagInvalidError):
        await validate_supplied_tag(conn, _ORG, _TAG, None, "AST_00042")


async def test_validate_supplied_tag_refuses_too_few_digits() -> None:
    conn, _fake = _conn(conflict=False)
    with pytest.raises(TagInvalidError):
        await validate_supplied_tag(conn, _ORG, _TAG, None, "AST-042")


async def test_validate_supplied_tag_accepts_overflow_beyond_the_configured_digits() -> None:
    conn, _fake = _conn(conflict=False)
    await validate_supplied_tag(conn, _ORG, _TAG, None, "AST-123456")


async def test_validate_supplied_tag_honors_the_category_prefix_override() -> None:
    wrong_conn, _wrong_fake = _conn(conflict=False)
    with pytest.raises(TagInvalidError):
        await validate_supplied_tag(wrong_conn, _ORG, _TAG, "LAP", "AST-00042")
    right_conn, _right_fake = _conn(conflict=False)
    await validate_supplied_tag(right_conn, _ORG, _TAG, "LAP", "LAP-00042")
