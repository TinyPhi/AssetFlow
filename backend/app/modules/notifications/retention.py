# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Delete notices past their retention, one organization at a time (§B13.5, M1.5-T3)."""

from __future__ import annotations

from datetime import timedelta

from app.core import clock
from app.core.db import Connection, Pool
from workers.sweep import for_each_active_organization

__all__ = ["TASK_NAME", "run"]

TASK_NAME = "notifications_retention"


async def run(pool: Pool, *, retention_days: int) -> None:
    """Delete every notice older than `retention_days`, per organization (§B13.5)."""
    cutoff = clock.now() - timedelta(days=retention_days)

    async def _delete_old(conn: Connection, _organization_id: object) -> None:
        await conn.execute("DELETE FROM public.notifications WHERE created_at < $1", cutoff)

    await for_each_active_organization(pool, _delete_old)
