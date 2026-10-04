# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Hand planned notification intents to the channels that send them (§B6.3, M1.5-T2).

A stub for now: P6-03 (in-app) and P6-06b (sender, retries, dead letter) implement the real queue.
Until then, intents are accepted and discarded - the automation subscriber that calls this is
still idempotent (`processed_events`), so nothing is lost silently more than once.
"""

from __future__ import annotations

from app.core.db import Connection
from app.engines.automation.planner import NotificationIntent

__all__ = ["enqueue"]


async def enqueue(conn: Connection, intents: list[NotificationIntent]) -> None:
    """Accept `intents` for delivery. Replaced by the real queue in P6-03/P6-06b."""
    return
