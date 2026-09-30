# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""UUIDv7 generation following RFC 9562 (§B10, decision D5).

Layout (RFC 9562 §5.7) with the §6.2 "Method 1" fixed-length dedicated counter:

    unix_ts_ms (48) | ver=7 (4) | rand_a = 12-bit counter | var=0b10 (2) | rand_b (62 random bits)

Within one process every generated value is strictly greater than the previous one:

* a new millisecond reseeds the counter with a random value whose top bit is 0, leaving at
  least 2048 increments before overflow;
* the same millisecond (or a clock that went backwards) increments the counter and keeps the
  last timestamp, so ordering never follows the wall clock backwards;
* a counter overflow advances the stored timestamp by one millisecond and reseeds the counter.
"""

from __future__ import annotations

import os
import secrets
import threading
import time
from uuid import UUID

_COUNTER_BITS = 12
_COUNTER_MAX = (1 << _COUNTER_BITS) - 1
_COUNTER_SEED_MASK = (1 << (_COUNTER_BITS - 1)) - 1  # top counter bit 0 on reseed
_RAND_B_BITS = 62
_TIMESTAMP_MASK = (1 << 48) - 1

_lock = threading.Lock()
_last_ms = -1
_counter = 0


def _reset_after_fork() -> None:
    """Give a forked child a fresh lock; a lock held by another thread at fork time never releases."""
    global _lock  # noqa: PLW0603 - module-level generator state is the point of this module
    _lock = threading.Lock()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_reset_after_fork)


def _next_state(now_ms: int) -> tuple[int, int]:
    """Advance the generator state for the current clock reading; caller holds the lock."""
    global _last_ms, _counter  # noqa: PLW0603 - see _reset_after_fork
    if now_ms > _last_ms:
        _last_ms = now_ms
        _counter = secrets.randbits(_COUNTER_BITS) & _COUNTER_SEED_MASK
    else:
        # Same millisecond, or the clock moved backwards: keep the last timestamp and count on.
        _counter += 1
        if _counter > _COUNTER_MAX:
            _last_ms += 1
            _counter = secrets.randbits(_COUNTER_BITS) & _COUNTER_SEED_MASK
    return _last_ms, _counter


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _build(unix_ms: int, counter: int, rand_b: int) -> UUID:
    value = (unix_ms & _TIMESTAMP_MASK) << 80
    value |= 0x7 << 76
    value |= (counter & _COUNTER_MAX) << 64
    value |= 0b10 << 62
    value |= rand_b & ((1 << _RAND_B_BITS) - 1)
    return UUID(int=value)


def uuid7() -> UUID:
    """Return a new UUIDv7, strictly greater than every earlier value from this process."""
    rand_b = secrets.randbits(_RAND_B_BITS)
    with _lock:
        unix_ms, counter = _next_state(_now_ms())
    return _build(unix_ms, counter, rand_b)


def uuid7_str() -> str:
    """Return a new UUIDv7 as a canonical lowercase string."""
    return str(uuid7())
