# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Audit partition maintenance and health checking (§2138)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import asyncpg

type DbConn = asyncpg.Connection[asyncpg.Record] | asyncpg.pool.PoolConnectionProxy[asyncpg.Record]


def next_month_name(base: datetime) -> str:
    """Format partition table name for the month after base."""
    y, m = (base.year + 1, 1) if base.month == 12 else (base.year, base.month + 1)
    return f"audit_events_{y}_{m:02d}"


async def maintain_partitions(
    conn: DbConn, *, base_date: datetime | None = None, months_ahead: int = 3
) -> list[str]:
    """Invoke stored procedure to ensure the next `months_ahead` partitions exist (§2138)."""
    ts = base_date or datetime.now(UTC)
    res = await conn.fetchval("SELECT platform.maintain_audit_partitions($1, $2)", ts, months_ahead)
    return list(res or [])


async def check_partition_health(conn: DbConn, *, base_date: datetime | None = None) -> dict[str, Any]:
    """Check that DEFAULT partition is empty and next month's partition is prepared (§2138)."""
    ts = base_date or datetime.now(UTC)
    sql = (
        "SELECT healthy, default_rows, next_partition_exists, next_partition_name, alert "
        "FROM platform.audit_partition_health($1)"
    )
    r = await conn.fetchrow(sql, ts)
    if r is not None:
        return dict(r)
    return {
        "healthy": False,
        "default_rows": 0,
        "next_partition_name": next_month_name(ts),
        "next_partition_exists": False,
        "alert": True,
    }
