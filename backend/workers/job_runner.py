# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""On-demand background jobs with time and memory limits (§B9.3 "Job runner").

A job is started by an outbox event subscription the owning module registers (no module uses this
yet; bulk import stays synchronous in M1.4, §B9.3). `JobRunner.register_job` wraps a handler with a
time limit (`asyncio.timeout`) and, on Linux, a memory limit enforced in a short-lived child process
(`resource.setrlimit(RLIMIT_AS)`, so a handler cannot exceed it by catching and ignoring the error).
On any other platform only the time limit applies; registering a job there logs a warning once.

A memory-limited handler must be a plain, importable top-level ``async def`` (never a closure or a
bound method): the child process is started fresh (``multiprocessing``'s ``spawn`` context) and
receives the handler by reference, the same way any other argument to the new process is sent. The
handler receives its own freshly opened connection, stamped with the job's organization before the
handler runs, and never touches the worker's connection pool — nothing from the pool can cross a
process boundary.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import multiprocessing
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from multiprocessing.connection import Connection as PipeConnection
from typing import Any, Protocol
from uuid import UUID

import asyncpg

from app.core.db import DatabaseSettings, Pool, SecretResolver, resolve_role_password, worker_context
from app.core.problems import JobMemoryLimitError, JobTimeLimitError

logger = logging.getLogger(__name__)

SPAN_NAME = "worker.job_runner.run"

#: `resource.setrlimit(RLIMIT_AS, ...)` only exists on Linux; this is the container target (§B9.3).
MEMORY_LIMIT_SUPPORTED = sys.platform == "linux"


class JobConnection(Protocol):
    """What a job handler needs from its connection, whether pooled or opened fresh in a child."""

    async def execute(self, query: str, *args: object) -> str: ...
    async def fetch(self, query: str, *args: object) -> list[asyncpg.Record]: ...
    async def fetchval(self, query: str, *args: object) -> Any: ...
    async def fetchrow(self, query: str, *args: object) -> asyncpg.Record | None: ...


JobHandler = Callable[[JobConnection, UUID, dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class JobSpec:
    """One registered job type and its limits."""

    job_type: str
    handler: JobHandler
    time_limit_seconds: float
    memory_limit_mb: int


@dataclass
class JobRunner:
    """Registered job types, each run under its own time and memory limit (§B9.3)."""

    _by_type: dict[str, JobSpec] = field(default_factory=dict)

    def register_job(
        self,
        job_type: str,
        handler: JobHandler,
        *,
        time_limit_seconds: float,
        memory_limit_mb: int,
    ) -> None:
        """Register `handler` as the implementation of `job_type`."""
        if job_type in self._by_type:
            raise ValueError(f"job type {job_type!r} is already registered")
        if not MEMORY_LIMIT_SUPPORTED:
            logger.warning(
                "worker.job_runner.memory_limit_unsupported",
                extra={"job_type": job_type, "platform": sys.platform},
            )
        self._by_type[job_type] = JobSpec(job_type, handler, time_limit_seconds, memory_limit_mb)

    def get(self, job_type: str) -> JobSpec | None:
        """Return the spec of `job_type`, or None if nothing is registered for it."""
        return self._by_type.get(job_type)


def default_runner() -> JobRunner:
    """The job types the running worker knows. Later plans register theirs here."""
    return JobRunner()


async def run_job(
    pool: Pool,
    *,
    database: DatabaseSettings,
    resolve_secret: SecretResolver,
    spec: JobSpec,
    organization_id: UUID,
    payload: dict[str, Any],
) -> None:
    """Run one job under its time limit, and its memory limit where the platform supports it.

    Raises `JobTimeLimitError` or `JobMemoryLimitError` on a limit; any other failure from the
    handler propagates as it was raised (in-process) or as its class name (child process) so the
    caller records it exactly like any other subscriber failure.
    """
    try:
        async with asyncio.timeout(spec.time_limit_seconds):
            if MEMORY_LIMIT_SUPPORTED:
                await _run_memory_limited(database, resolve_secret, spec, organization_id, payload)
            else:
                async with worker_context(pool, organization_id) as conn:
                    await spec.handler(conn, organization_id, payload)
    except TimeoutError as exc:
        # asyncio.timeout's __aexit__ converts the cancellation into TimeoutError only after the
        # `async with` block above has fully exited, so this must wrap it, not sit inside it.
        raise JobTimeLimitError() from exc


@dataclass(frozen=True)
class _ChildJobRequest:
    """Everything the memory-limited child process needs; every field is picklable on its own."""

    handler: JobHandler
    host: str
    port: int
    dbname: str
    user: str
    password: str
    organization_id: UUID
    payload: dict[str, Any]
    memory_limit_mb: int


def _child_main(request: _ChildJobRequest, report: PipeConnection) -> None:
    """Entry point of the memory-limited child process (Linux only; see `MEMORY_LIMIT_SUPPORTED`).

    Sets the memory limit before anything else runs, then opens its own connection (never the
    parent's pool) and calls the handler. Reports the outcome on `report`: None for success, or the
    failure's error class name (`"MemoryError"` included).
    """
    import resource  # noqa: PLC0415 - Linux only; this function never runs elsewhere

    limit_bytes = request.memory_limit_mb * 1024 * 1024
    with contextlib.suppress(ValueError, OSError):
        resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))
    try:
        asyncio.run(_child_async_main(request))
    except Exception as exc:  # noqa: BLE001 - reported to the parent, including MemoryError, never raised here
        report.send(type(exc).__name__)
    else:
        report.send(None)
    finally:
        report.close()


async def _child_async_main(request: _ChildJobRequest) -> None:
    conn = await asyncpg.connect(
        host=request.host,
        port=request.port,
        database=request.dbname,
        user=request.user,
        password=request.password,
        server_settings={"application_name": "assetflow-worker-job"},
    )
    try:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config('app.organization_id', $1, true)", str(request.organization_id)
            )
            await request.handler(conn, request.organization_id, request.payload)
    finally:
        await conn.close()


async def _run_memory_limited(
    database: DatabaseSettings,
    resolve_secret: SecretResolver,
    spec: JobSpec,
    organization_id: UUID,
    payload: dict[str, Any],
) -> None:
    password = await resolve_role_password(database, "worker", resolve_secret)
    request = _ChildJobRequest(
        handler=spec.handler,
        host=database.host,
        port=database.port,
        dbname=database.name,
        user=database.worker.user,
        password=password,
        organization_id=organization_id,
        payload=payload,
        memory_limit_mb=spec.memory_limit_mb,
    )
    ctx = multiprocessing.get_context("spawn")
    parent_report, child_report = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_child_main, args=(request, child_report))
    process.start()
    child_report.close()  # only the child writes; close the parent's copy of that end
    loop = asyncio.get_running_loop()
    try:
        try:
            outcome = await loop.run_in_executor(None, parent_report.recv)
        except EOFError:
            # The child died without reporting - most likely the kernel enforced the limit harder
            # than RLIMIT_AS could catch. Treated the same as a caught MemoryError.
            outcome = "MemoryError"
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
            process.join()
        parent_report.close()
    if outcome == "MemoryError":
        raise JobMemoryLimitError()
    if outcome is not None:
        raise RuntimeError(f"job {spec.job_type!r} failed in its memory-limited process: {outcome}")
