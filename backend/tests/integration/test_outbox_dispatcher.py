# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The outbox dispatcher on a real PostgreSQL (§B9.3, §B10, §C8.4 worker jobs).

Rows are seeded and inspected as the superuser (it bypasses RLS); the dispatcher itself runs as the
`assetflow_worker` role through `app.core.db`, exactly as in production.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any

import asyncpg
import pytest
from pg_harness import IsolationDb, PoolFactory

from app.core.db import Connection
from app.core.ids import uuid7
from app.providers.telemetry.noop import NoOpTelemetryProvider
from workers.outbox_dispatcher import (
    DEAD_LETTER_METRIC,
    LAG_METRIC,
    DispatcherOptions,
    claim_batch,
    run_once,
    run_subscribers,
)
from workers.subscribers import OutboxEvent, SubscriberRegistry

EFFECT_ACTION = "test.worker_effect"
OPTIONS = DispatcherOptions(batch_size=50, reclaim_after_seconds=300, max_attempts=3)


@pytest.fixture
async def admin(isolation_db: IsolationDb) -> AsyncIterator[asyncpg.Connection[asyncpg.Record]]:
    conn = await asyncpg.connect(isolation_db.admin_dsn)
    await conn.execute("DELETE FROM public.outbox")
    yield conn
    await conn.execute("DELETE FROM public.outbox")
    await conn.close()


async def seed(
    admin: asyncpg.Connection[asyncpg.Record], org: uuid.UUID, event_type: str = "item.created"
) -> uuid.UUID:
    event_id = uuid7()
    await admin.execute(
        "INSERT INTO public.outbox (id, organization_id, event_type, aggregate_type, aggregate_id) "
        "VALUES ($1, $2, $3, 'item', $4)",
        event_id,
        org,
        event_type,
        uuid7(),
    )
    return event_id


async def effects(admin: asyncpg.Connection[asyncpg.Record], event_id: uuid.UUID) -> int:
    return int(
        await admin.fetchval(
            "SELECT count(*) FROM public.audit_events WHERE action = $1 AND entity_id = $2",
            EFFECT_ACTION,
            event_id,
        )
    )


async def effect_handler(conn: Connection, event: OutboxEvent) -> None:
    """A subscriber whose database effect is one audit row per event."""
    await conn.execute(
        "INSERT INTO public.audit_events (id, organization_id, action, entity_type, entity_id) "
        "VALUES ($1, $2, $3, 'event', $4)",
        uuid7(),
        event.organization_id,
        EFFECT_ACTION,
        event.id,
    )


def registry_with(handler: Any = effect_handler, event_type: str = "item.created") -> SubscriberRegistry:
    registry = SubscriberRegistry()
    registry.subscribe(event_type, "test-consumer", handler)
    return registry


async def row(admin: asyncpg.Connection[asyncpg.Record], event_id: uuid.UUID) -> asyncpg.Record:
    found = await admin.fetchrow("SELECT * FROM public.outbox WHERE id = $1", event_id)
    assert found is not None
    return found


async def test_claim_run_and_record_across_organizations(
    make_pool: PoolFactory, isolation_db: IsolationDb, admin: asyncpg.Connection[asyncpg.Record]
) -> None:
    pool = await make_pool("worker")
    id_a = await seed(admin, isolation_db.org_a)
    id_b = await seed(admin, isolation_db.org_b)
    handled = await run_once(pool, registry_with(), "worker-1", OPTIONS)
    assert handled == 2
    for event_id in (id_a, id_b):
        done = await row(admin, event_id)
        assert done["processed_at"] is not None
        assert done["claimed_by"] is None
        assert done["attempts"] == 1
        assert await effects(admin, event_id) == 1


async def test_running_twice_produces_one_effect(
    make_pool: PoolFactory, isolation_db: IsolationDb, admin: asyncpg.Connection[asyncpg.Record]
) -> None:
    pool = await make_pool("worker")
    event_id = await seed(admin, isolation_db.org_a)
    registry = registry_with()
    assert await run_once(pool, registry, "worker-1", OPTIONS) == 1
    assert await run_once(pool, registry, "worker-1", OPTIONS) == 0
    # A redelivery of the same event (queue state lost) is skipped by processed_events.
    await admin.execute("UPDATE public.outbox SET processed_at = NULL WHERE id = $1", event_id)
    assert await run_once(pool, registry, "worker-1", OPTIONS) == 1
    assert await effects(admin, event_id) == 1


async def test_two_workers_at_once_handle_each_row_once(
    make_pool: PoolFactory, isolation_db: IsolationDb, admin: asyncpg.Connection[asyncpg.Record]
) -> None:
    ids = [await seed(admin, isolation_db.org_a if i % 2 else isolation_db.org_b) for i in range(24)]
    seen: list[uuid.UUID] = []

    async def counting(conn: Connection, event: OutboxEvent) -> None:
        seen.append(event.id)
        await effect_handler(conn, event)

    registry = registry_with(counting)
    options = DispatcherOptions(batch_size=8, reclaim_after_seconds=300, max_attempts=3)
    pool_1, pool_2 = await make_pool("worker"), await make_pool("worker")

    async def drain(pool: Any, name: str) -> None:
        while await run_once(pool, registry, name, options):
            pass

    await asyncio.gather(drain(pool_1, "worker-1"), drain(pool_2, "worker-2"))
    assert sorted(seen) == sorted(ids)
    assert [await effects(admin, event_id) for event_id in ids] == [1] * len(ids)


async def test_stale_claim_is_reclaimed_and_fresh_claim_is_not(
    make_pool: PoolFactory, isolation_db: IsolationDb, admin: asyncpg.Connection[asyncpg.Record]
) -> None:
    pool = await make_pool("worker")
    event_id = await seed(admin, isolation_db.org_a)
    claimed, _lag = await claim_batch(pool, "worker-1", OPTIONS)
    assert [event.id for event in claimed] == [event_id]

    assert await run_once(pool, registry_with(), "worker-2", OPTIONS) == 0  # claim is fresh

    await admin.execute(
        "UPDATE public.outbox SET claimed_at = now() - interval '6 minutes' WHERE id = $1", event_id
    )
    assert await run_once(pool, registry_with(), "worker-2", OPTIONS) == 1
    done = await row(admin, event_id)
    assert done["processed_at"] is not None
    assert done["attempts"] == 2


async def test_failure_counts_attempts_and_dead_letters_at_the_limit(
    make_pool: PoolFactory, isolation_db: IsolationDb, admin: asyncpg.Connection[asyncpg.Record]
) -> None:
    pool = await make_pool("worker")
    event_id = await seed(admin, isolation_db.org_a)

    async def failing(conn: Connection, event: OutboxEvent) -> None:
        raise RuntimeError("could not reach jane.doe@example.org")

    registry = registry_with(failing)
    for attempt in (1, 2):
        assert await run_once(pool, registry, "worker-1", OPTIONS) == 1
        failed = await row(admin, event_id)
        assert failed["attempts"] == attempt
        assert failed["dead_lettered_at"] is None
        assert failed["claimed_by"] is None
    assert await run_once(pool, registry, "worker-1", OPTIONS) == 1
    dead = await row(admin, event_id)
    assert dead["attempts"] == 3
    assert dead["dead_lettered_at"] is not None
    assert dead["processed_at"] is None
    assert dead["last_error"] == "RuntimeError"  # the class only, never the message
    assert await run_once(pool, registry, "worker-1", OPTIONS) == 0


async def test_kill_between_effect_and_record_still_gives_one_effect(
    make_pool: PoolFactory, isolation_db: IsolationDb, admin: asyncpg.Connection[asyncpg.Record]
) -> None:
    pool = await make_pool("worker")
    event_id = await seed(admin, isolation_db.org_a)
    registry = registry_with()
    claimed, _lag = await claim_batch(pool, "worker-1", OPTIONS)
    await run_subscribers(pool, registry, claimed[0])  # the effect commits, then the worker is killed
    assert (await row(admin, event_id))["processed_at"] is None
    assert await effects(admin, event_id) == 1

    await admin.execute(
        "UPDATE public.outbox SET claimed_at = now() - interval '6 minutes' WHERE id = $1", event_id
    )
    assert await run_once(pool, registry, "worker-2", OPTIONS) == 1
    assert (await row(admin, event_id))["processed_at"] is not None
    assert await effects(admin, event_id) == 1


async def test_event_that_keeps_killing_the_worker_is_dead_lettered(
    make_pool: PoolFactory, isolation_db: IsolationDb, admin: asyncpg.Connection[asyncpg.Record]
) -> None:
    pool = await make_pool("worker")
    event_id = await seed(admin, isolation_db.org_a)
    await admin.execute(
        "UPDATE public.outbox SET attempts = 3, claimed_by = 'worker-9', "
        "claimed_at = now() - interval '6 minutes' WHERE id = $1",
        event_id,
    )
    assert await run_once(pool, registry_with(), "worker-2", OPTIONS) == 0
    dead = await row(admin, event_id)
    assert dead["dead_lettered_at"] is not None
    assert dead["last_error"] == "ClaimExpired"
    assert dead["claimed_by"] is None


async def test_subscribers_run_outside_the_claim_transaction_under_the_event_organization(
    make_pool: PoolFactory, isolation_db: IsolationDb, admin: asyncpg.Connection[asyncpg.Record]
) -> None:
    pool = await make_pool("worker")
    await seed(admin, isolation_db.org_b)
    observed: dict[str, Any] = {}

    async def probe(conn: Connection, event: OutboxEvent) -> None:
        observed["org"] = await conn.fetchval("SELECT current_setting('app.organization_id')")
        observed["open_elsewhere"] = await conn.fetchval(
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE usename = current_user AND pid <> pg_backend_pid() AND state LIKE 'idle in transaction%'"
        )

    assert await run_once(pool, registry_with(probe), "worker-1", OPTIONS) == 1
    assert observed["org"] == str(isolation_db.org_b)
    assert observed["open_elsewhere"] == 0


async def test_events_without_subscribers_are_marked_processed(
    make_pool: PoolFactory, isolation_db: IsolationDb, admin: asyncpg.Connection[asyncpg.Record]
) -> None:
    pool = await make_pool("worker")
    event_id = await seed(admin, isolation_db.org_a, "nobody.listens")
    assert await run_once(pool, registry_with(), "worker-1", OPTIONS) == 1
    assert (await row(admin, event_id))["processed_at"] is not None


async def test_stop_releases_claimed_rows_without_counting_an_attempt(
    make_pool: PoolFactory, isolation_db: IsolationDb, admin: asyncpg.Connection[asyncpg.Record]
) -> None:
    pool = await make_pool("worker")
    ids = [await seed(admin, isolation_db.org_a) for _ in range(3)]
    assert await run_once(pool, registry_with(), "worker-1", OPTIONS, should_stop=lambda: True) == 0
    for event_id in ids:
        released = await row(admin, event_id)
        assert released["claimed_by"] is None
        assert released["attempts"] == 0
        assert released["processed_at"] is None


class _Metrics(NoOpTelemetryProvider):
    def __init__(self) -> None:
        super().__init__()
        self.recorded: list[tuple[str, float]] = []

    def record_metric(self, name: str, value: float, tags: dict[str, str] | None = None) -> None:
        assert not tags  # no tags at all: nothing personal can leak into a metric
        self.recorded.append((name, value))


async def test_lag_and_dead_letter_metrics_are_recorded(
    make_pool: PoolFactory, isolation_db: IsolationDb, admin: asyncpg.Connection[asyncpg.Record]
) -> None:
    pool = await make_pool("worker")
    event_id = await seed(admin, isolation_db.org_a)
    await admin.execute(
        "UPDATE public.outbox SET created_at = now() - interval '10 seconds' WHERE id = $1", event_id
    )

    async def failing(conn: Connection, event: OutboxEvent) -> None:
        raise ValueError

    telemetry = _Metrics()
    options = DispatcherOptions(batch_size=10, reclaim_after_seconds=300, max_attempts=1)
    await run_once(pool, registry_with(failing), "worker-1", options, telemetry=telemetry)
    lag = [value for name, value in telemetry.recorded if name == LAG_METRIC]
    assert lag and lag[0] >= 10
    assert (DEAD_LETTER_METRIC, 1.0) in telemetry.recorded
