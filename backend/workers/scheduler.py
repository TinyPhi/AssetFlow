# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Periodic jobs, run once per tick across every worker replica (§B9.3 "Job runner").

Each periodic job is guarded by a PostgreSQL session-level advisory lock
(`pg_try_advisory_lock`), taken on a dedicated direct connection (not PgBouncer: a session-level
lock does not survive a pooled connection being handed to another session between statements).
Only one replica runs a given job on a given tick; the others skip it. Jobs are idempotent anyway
(§B9.3), so a missed tick from a lock race is not a correctness problem, only a scheduling one.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.core import clock
from app.core.db import DirectConnection

logger = logging.getLogger(__name__)

PeriodicHandler = Callable[[], Awaitable[None]]


@dataclass
class _PeriodicJob:
    name: str
    interval: timedelta
    handler: PeriodicHandler
    next_run: datetime


@dataclass
class Scheduler:
    """Periodic jobs ticked from the worker's dispatch loop, guarded by an advisory lock.

    `conn` is the worker's own direct connection (the same one used for LISTEN), so taking and
    releasing the lock does not need a separate connection per tick.
    """

    conn: DirectConnection
    _jobs: list[_PeriodicJob] = field(default_factory=list)

    def register_periodic(self, name: str, interval: timedelta, handler: PeriodicHandler) -> None:
        """Register `handler` to run at most once every `interval`, across all replicas."""
        if any(job.name == name for job in self._jobs):
            raise ValueError(f"periodic job {name!r} is already registered")
        self._jobs.append(_PeriodicJob(name, interval, handler, clock.now()))

    async def tick(self) -> None:
        """Run every due job whose advisory lock this replica can acquire."""
        now = clock.now()
        for job in self._jobs:
            if now < job.next_run:
                continue
            job.next_run = now + job.interval
            acquired = await self.conn.fetchval("SELECT pg_try_advisory_lock(hashtext($1))", job.name)
            if not acquired:
                continue
            try:
                await job.handler()
            except Exception as exc:  # noqa: BLE001 - one job's failure must not stop the others
                logger.warning(
                    "worker.scheduler.job_failed",
                    extra={"job_name": job.name, "error_code": type(exc).__name__},
                )
            finally:
                await self.conn.execute("SELECT pg_advisory_unlock(hashtext($1))", job.name)
