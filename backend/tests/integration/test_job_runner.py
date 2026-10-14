# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The job runner's time and memory limits, against a real PostgreSQL (§B9.3 "Job runner")."""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass

import asyncpg
import pytest
from job_runner_handlers import (
    PROBE_CONSUMER,
    allocates_too_much_memory,
    counts_other_organization_then_records,
    sleeps_forever,
    succeeds,
)
from pg_harness import IsolationDb, PoolFactory

from app.core.db import DatabaseSettings
from app.core.ids import uuid7
from app.core.problems import JobMemoryLimitError, JobTimeLimitError
from workers.job_runner import JobSpec, run_job


@dataclass(frozen=True)
class _RoleCfg:
    user: str
    password: str


@dataclass(frozen=True)
class _DbSettings:
    """A `DatabaseSettings` built from the isolation harness's own users (literal passwords)."""

    host: str
    port: int
    name: str
    api: _RoleCfg
    worker: _RoleCfg
    migrator: _RoleCfg
    behind_pgbouncer: bool = False
    statement_timeout_ms: int = 15000
    idle_in_transaction_timeout_ms: int = 30000
    pool_min: int = 1
    pool_max: int = 1
    connect_timeout_s: float = 30.0
    acquire_timeout_s: float = 10.0


def _database_settings(isolation_db: IsolationDb) -> DatabaseSettings:
    def role(kind: str) -> _RoleCfg:
        user = isolation_db.users[kind]
        return _RoleCfg(user.name, user.password)

    return _DbSettings(
        host=isolation_db.server.host,
        port=isolation_db.server.port,
        name=isolation_db.database,
        api=role("api"),
        worker=role("worker"),
        migrator=role("migrator"),
    )


async def _unused_resolve_secret(ref: str) -> str:
    raise AssertionError("the test passes a literal password; resolve_secret must not be called")


@pytest.fixture
async def admin(isolation_db: IsolationDb) -> AsyncIterator[asyncpg.Connection[asyncpg.Record]]:
    conn = await asyncpg.connect(isolation_db.admin_dsn)
    await conn.execute(
        "DELETE FROM public.processed_events WHERE consumer_name LIKE $1", f"{PROBE_CONSUMER}%"
    )
    yield conn
    await conn.execute(
        "DELETE FROM public.processed_events WHERE consumer_name LIKE $1", f"{PROBE_CONSUMER}%"
    )
    await conn.close()


async def test_a_job_within_its_limits_succeeds(
    make_pool: PoolFactory, isolation_db: IsolationDb, admin: asyncpg.Connection[asyncpg.Record]
) -> None:
    pool = await make_pool("worker")
    spec = JobSpec("succeeds", succeeds, time_limit_seconds=5, memory_limit_mb=256)
    await run_job(
        pool,
        database=_database_settings(isolation_db),
        resolve_secret=_unused_resolve_secret,
        spec=spec,
        organization_id=isolation_db.org_a,
        payload={},
    )
    count = await admin.fetchval(
        "SELECT count(*) FROM public.processed_events WHERE organization_id = $1 AND consumer_name = $2",
        isolation_db.org_a,
        PROBE_CONSUMER,
    )
    assert count == 1


async def test_a_job_over_its_time_limit_is_stopped(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    pool = await make_pool("worker")
    spec = JobSpec("sleeps_forever", sleeps_forever, time_limit_seconds=0.2, memory_limit_mb=256)
    with pytest.raises(JobTimeLimitError):
        await run_job(
            pool,
            database=_database_settings(isolation_db),
            resolve_secret=_unused_resolve_secret,
            spec=spec,
            organization_id=isolation_db.org_a,
            payload={},
        )


@pytest.mark.skipif(sys.platform != "linux", reason="RLIMIT_AS is Linux only")
async def test_a_job_over_its_memory_limit_is_stopped(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    pool = await make_pool("worker")
    spec = JobSpec(
        "allocates_too_much", allocates_too_much_memory, time_limit_seconds=10, memory_limit_mb=128
    )
    with pytest.raises(JobMemoryLimitError):
        await run_job(
            pool,
            database=_database_settings(isolation_db),
            resolve_secret=_unused_resolve_secret,
            spec=spec,
            organization_id=isolation_db.org_a,
            payload={"megabytes": 300},
        )


@pytest.mark.skipif(sys.platform != "linux", reason="RLIMIT_AS is Linux only")
async def test_a_memory_limited_job_for_org_a_cannot_see_org_b_rows(
    make_pool: PoolFactory, isolation_db: IsolationDb, admin: asyncpg.Connection[asyncpg.Record]
) -> None:
    """The memory-limited child process opens its own connection; it must still be org-scoped."""
    await admin.execute(
        "INSERT INTO public.processed_events (id, organization_id, consumer_name, event_id) "
        "VALUES ($1, $2, 'org-b-only', $3)",
        uuid7(),
        isolation_db.org_b,
        uuid7(),
    )
    try:
        pool = await make_pool("worker")
        spec = JobSpec(
            "counts_other_org",
            counts_other_organization_then_records,
            time_limit_seconds=5,
            memory_limit_mb=256,
        )
        await run_job(
            pool,
            database=_database_settings(isolation_db),
            resolve_secret=_unused_resolve_secret,
            spec=spec,
            organization_id=isolation_db.org_a,
            payload={"other_organization_id": isolation_db.org_b},
        )
        recorded = await admin.fetchval(
            "SELECT consumer_name FROM public.processed_events "
            "WHERE organization_id = $1 AND consumer_name LIKE $2",
            isolation_db.org_a,
            f"{PROBE_CONSUMER}:%",
        )
        assert recorded == f"{PROBE_CONSUMER}:visible_other_org_rows=0"
    finally:
        await admin.execute("DELETE FROM public.processed_events WHERE consumer_name = 'org-b-only'")
