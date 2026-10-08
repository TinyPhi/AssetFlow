# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The one place application logic reads the current time (§C8.2).

Tests freeze it with ``time-machine`` (``time_machine.travel(...)``), which patches the system
clock that :func:`datetime.now` reads, so no test double is needed here: code that calls
:func:`now` sees the frozen time automatically.
"""

from __future__ import annotations

from datetime import UTC, datetime


def now() -> datetime:
    """Return the current time (UTC, timezone-aware)."""
    return datetime.now(UTC)
