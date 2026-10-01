# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""UUIDv7 generator: RFC 9562 layout and strict monotonicity (§6.2 method 1)."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from itertools import pairwise
from uuid import UUID

import pytest

from app.core import ids
from app.core.ids import uuid7, uuid7_str


def _ms(u: UUID) -> int:
    return u.int >> 80


def _counter(u: UUID) -> int:
    return (u.int >> 64) & 0xFFF


@pytest.fixture
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[int]]:
    """A controllable clock in milliseconds; also resets the generator state."""
    now = [1_700_000_000_000]
    monkeypatch.setattr(ids, "_now_ms", lambda: now[0])
    monkeypatch.setattr(ids, "_last_ms", -1)
    monkeypatch.setattr(ids, "_counter", 0)
    yield now


def test_layout_version_and_variant() -> None:
    u = uuid7()
    assert u.version == 7
    assert u.variant == "specified in RFC 4122"
    s = uuid7_str()
    assert len(s) == 36
    assert s[14] == "7"
    assert s[19] in "89ab"


def test_100k_strictly_monotonic_and_unique() -> None:
    values = [uuid7() for _ in range(100_000)]
    assert all(a < b for a, b in pairwise(values))
    assert len({v.bytes for v in values}) == len(values)
    as_str = [str(v) for v in values]
    assert as_str == sorted(as_str)


def test_same_millisecond_increments_counter(frozen_clock: list[int]) -> None:
    a, b, c = uuid7(), uuid7(), uuid7()
    assert _ms(a) == _ms(b) == _ms(c) == frozen_clock[0]
    assert _counter(b) == _counter(a) + 1
    assert _counter(c) == _counter(b) + 1
    assert _counter(a) < 0x800  # a reseed leaves the top counter bit clear


def test_clock_going_backwards_stays_monotonic(frozen_clock: list[int]) -> None:
    first = uuid7()
    frozen_clock[0] -= 5_000
    second = uuid7()
    assert second > first
    assert _ms(second) == _ms(first)


def test_counter_overflow_advances_timestamp(
    frozen_clock: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    first = uuid7()
    monkeypatch.setattr(ids, "_counter", 0xFFF)
    second = uuid7()
    assert _ms(second) == _ms(first) + 1
    assert second > first
    assert uuid7() > second


def test_threads_never_collide_and_each_thread_is_ordered() -> None:
    per_thread: list[list[UUID]] = [[] for _ in range(8)]

    def work(out: list[UUID]) -> None:
        out.extend(uuid7() for _ in range(5_000))

    threads = [threading.Thread(target=work, args=(out,)) for out in per_thread]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    all_values = [v for out in per_thread for v in out]
    assert len(set(all_values)) == len(all_values)
    for out in per_thread:
        assert all(a < b for a, b in pairwise(out))
