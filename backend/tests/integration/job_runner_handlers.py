# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Job handlers for `test_job_runner.py`, in their own module so a memory-limited job's handler is
a plain, importable top-level function the spawned child process can receive by reference.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from app.core.ids import uuid7
from workers.job_runner import JobConnection

PROBE_CONSUMER = "job-runner-probe"


async def succeeds(conn: JobConnection, organization_id: UUID, payload: dict[str, Any]) -> None:
    """Writes one row tagged with the organization it was called with."""
    await conn.execute(
        "INSERT INTO public.processed_events (id, organization_id, consumer_name, event_id) "
        "VALUES ($1, $2, $3, $4)",
        uuid7(),
        organization_id,
        PROBE_CONSUMER,
        uuid7(),
    )


async def sleeps_forever(conn: JobConnection, organization_id: UUID, payload: dict[str, Any]) -> None:
    """Never finishes, to exercise the time limit."""
    await asyncio.sleep(60)


async def allocates_too_much_memory(
    conn: JobConnection, organization_id: UUID, payload: dict[str, Any]
) -> None:
    """Allocates and touches well over a small `RLIMIT_AS`, to exercise the memory limit."""
    block = bytearray(payload.get("megabytes", 300) * 1024 * 1024)
    block[::4096] = bytes(len(block[::4096]))  # touch every page so the allocator cannot defer it


async def counts_other_organization_then_records(
    conn: JobConnection, organization_id: UUID, payload: dict[str, Any]
) -> None:
    """Counts rows of `payload["other_organization_id"]`, then records that count in its own row.

    Run as a job for one organization, this proves the job's connection is scoped the same way a
    normal request is: the count it can see of another organization's rows must be zero, whether
    the job ran in-process or in the memory-limited child process.
    """
    visible = await conn.fetchval(
        "SELECT count(*) FROM public.processed_events WHERE organization_id = $1",
        payload["other_organization_id"],
    )
    await conn.execute(
        "INSERT INTO public.processed_events (id, organization_id, consumer_name, event_id) "
        "VALUES ($1, $2, $3, $4)",
        uuid7(),
        organization_id,
        f"{PROBE_CONSUMER}:visible_other_org_rows={visible}",
        uuid7(),
    )
