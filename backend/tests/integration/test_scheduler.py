# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The periodic scheduler's advisory lock, against a real PostgreSQL (§B9.3 "Job runner")."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta

import asyncpg
import pytest
import time_machine
from pg_harness import IsolationDb

from workers.scheduler import Scheduler


@pytest.fixture
async def worker_dsn(isolation_db: IsolationDb) -> str:
    user = isolation_db.users["worker"]
    return isolation_db.server.dsn(isolation_db.database, user.name, user.password)


@pytest.fixture
async def worker_conn(worker_dsn: str) -> AsyncIterator[asyncpg.Connection[asyncpg.Record]]:
    conn = await asyncpg.connect(worker_dsn)
    yield conn
    await conn.close()


async def test_a_due_job_runs_once_and_waits_out_its_interval(
    worker_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    scheduler = Scheduler(worker_conn)
    runs: list[str] = []
    with time_machine.travel("2026-01-01T00:00:00Z", tick=False) as traveller:
        scheduler.register_periodic("probe", timedelta(seconds=10), lambda: _record(runs, "probe"))
        await scheduler.tick()  # due immediately on registration
        assert runs == ["probe"]
        await scheduler.tick()  # not due yet
        assert runs == ["probe"]
        traveller.shift(timedelta(seconds=10))
        await scheduler.tick()
        assert runs == ["probe", "probe"]


async def test_a_failing_job_does_not_stop_the_scheduler_or_hold_the_lock(
    worker_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    scheduler = Scheduler(worker_conn)

    async def fails() -> None:
        raise ValueError("boom")

    with time_machine.travel("2026-01-01T00:00:00Z", tick=False):
        scheduler.register_periodic("flaky", timedelta(seconds=1), fails)
        await scheduler.tick()  # logged and swallowed, not raised
    held = await worker_conn.fetchval("SELECT pg_try_advisory_lock(hashtext('flaky'))")
    assert held is True  # the lock was released even though the job raised
    await worker_conn.execute("SELECT pg_advisory_unlock(hashtext('flaky'))")


async def test_two_schedulers_at_once_run_the_job_once_per_tick(worker_dsn: str) -> None:
    conn_a = await asyncpg.connect(worker_dsn)
    conn_b = await asyncpg.connect(worker_dsn)
    runs: list[str] = []
    overlap = asyncio.Event()

    async def holds_the_lock_briefly() -> None:
        # Gives the other scheduler's concurrent tick a window to try (and fail) the same lock,
        # proving real mutual exclusion rather than a lock released before the other side asks.
        runs.append("a")
        overlap.set()
        await asyncio.sleep(0.2)

    async def runs_if_it_gets_the_lock() -> None:
        await overlap.wait()
        runs.append("b")

    try:
        scheduler_a = Scheduler(conn_a)
        scheduler_b = Scheduler(conn_b)
        with time_machine.travel("2026-01-01T00:00:00Z", tick=False):
            scheduler_a.register_periodic("shared", timedelta(seconds=10), holds_the_lock_briefly)
            scheduler_b.register_periodic("shared", timedelta(seconds=10), runs_if_it_gets_the_lock)
            await asyncio.gather(scheduler_a.tick(), scheduler_b.tick())
        assert runs == ["a"]  # b's try_advisory_lock failed while a's tick still held it
    finally:
        await conn_a.close()
        await conn_b.close()


async def _record(runs: list[str], value: str) -> None:
    runs.append(value)
