# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Daily housekeeping: delete processed rows past their retention, per organization (§B9.3, §B13.5).

Deletes run under `worker_context(organization_id)`, so the standard organization-scoped row-level
security policy applies (the worker's wider "see everything" claim policies cover `SELECT` and
`UPDATE` on `outbox` only, never `DELETE`); each organization is its own short transaction, and a
failure in one does not stop the rest (`sweep.for_each_active_organization`).

Other modules add their own retention by registering through `HousekeepingRegistry` (for example
in-app notification retention, P6-03; expired exports, later).
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta

from app.core import clock
from app.core.db import Connection, Pool, platform_transaction
from app.modules.audit.housekeeping import maintain_partitions
from app.providers.telemetry.base import TelemetryProvider
from workers.sweep import for_each_active_organization

logger = logging.getLogger(__name__)

SPAN_NAME = "worker.housekeeping.run"
DELETED_ROWS_METRIC = "assetflow_housekeeping_deleted_rows_total"

OUTBOX_AND_PROCESSED_EVENTS_RETENTION = timedelta(days=7)

HousekeepingTask = Callable[[Pool], Awaitable[None]]


@dataclass
class HousekeepingRegistry:
    """Extra housekeeping tasks run on every tick, alongside the built-in outbox/audit ones."""

    _tasks: dict[str, HousekeepingTask] = field(default_factory=dict)

    def register_housekeeping_task(self, name: str, fn: HousekeepingTask) -> None:
        """Register `fn` to run once per housekeeping tick, under the given `name`."""
        if name in self._tasks:
            raise ValueError(f"housekeeping task {name!r} is already registered")
        self._tasks[name] = fn

    def task_names(self) -> list[str]:
        """The names of the extra tasks registered so far (for tests)."""
        return list(self._tasks)

    async def run_all(self, pool: Pool) -> None:
        """Run every registered task; one task's failure does not stop the others."""
        for name, task in self._tasks.items():
            try:
                await task(pool)
            except Exception as exc:  # noqa: BLE001 - one extra task's failure must not stop the rest
                logger.warning(
                    "worker.housekeeping.task_failed",
                    extra={"task_name": name, "error_code": type(exc).__name__},
                )


def default_registry() -> HousekeepingRegistry:
    """The extra housekeeping tasks of the running worker. Later plans register theirs here."""
    return HousekeepingRegistry()


def _affected(command_tag: str) -> int:
    # asyncpg's execute() returns a tag like "DELETE 3"; the row count is its last word.
    return int(command_tag.rsplit(" ", 1)[-1])


async def _delete_old_outbox(conn: Connection, telemetry: TelemetryProvider | None) -> None:
    cutoff = clock.now() - OUTBOX_AND_PROCESSED_EVENTS_RETENTION
    result = await conn.execute(
        "DELETE FROM public.outbox WHERE processed_at IS NOT NULL AND processed_at < $1", cutoff
    )
    if telemetry is not None:
        telemetry.record_metric(DELETED_ROWS_METRIC, float(_affected(result)), {"table": "outbox"})


async def _delete_old_processed_events(conn: Connection, telemetry: TelemetryProvider | None) -> None:
    cutoff = clock.now() - OUTBOX_AND_PROCESSED_EVENTS_RETENTION
    result = await conn.execute("DELETE FROM public.processed_events WHERE processed_at < $1", cutoff)
    if telemetry is not None:
        telemetry.record_metric(DELETED_ROWS_METRIC, float(_affected(result)), {"table": "processed_events"})


async def run_once(
    pool: Pool, registry: HousekeepingRegistry, *, telemetry: TelemetryProvider | None = None
) -> None:
    """Run the built-in retention deletes for every active organization, then the extra tasks.

    Audit partition upkeep (`maintain_partitions`) is platform-wide, not per-organization: it runs
    once under no organization context, through `platform.maintain_audit_partitions`, which the
    worker role may execute (unlike dropping an old partition, which stays an operator command,
    §B13.5 — this plan never drops a partition).
    """
    span = telemetry.start_span(SPAN_NAME) if telemetry is not None else contextlib.nullcontext()
    with span:

        async def _delete_both(conn: Connection, _organization_id: object) -> None:
            await _delete_old_outbox(conn, telemetry)
            await _delete_old_processed_events(conn, telemetry)

        await for_each_active_organization(pool, _delete_both)
        async with platform_transaction(pool) as conn:
            await maintain_partitions(conn)
        await registry.run_all(pool)
