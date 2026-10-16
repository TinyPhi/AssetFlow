# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Daily housekeeping against a real PostgreSQL (§B9.3, §B13.5)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta

import asyncpg
import pytest
import time_machine
from pg_harness import IsolationDb, PoolFactory

from app.core import clock
from app.core.ids import uuid7
from workers.housekeeping import HousekeepingRegistry, default_registry, run_once


@pytest.fixture
async def admin(isolation_db: IsolationDb) -> AsyncIterator[asyncpg.Connection[asyncpg.Record]]:
    conn = await asyncpg.connect(isolation_db.admin_dsn)
    await conn.execute("DELETE FROM public.outbox")
    await conn.execute("DELETE FROM public.processed_events")
    yield conn
    await conn.execute("DELETE FROM public.outbox")
    await conn.execute("DELETE FROM public.processed_events")
    await conn.close()


async def _seed_outbox(
    admin: asyncpg.Connection[asyncpg.Record], org: uuid.UUID, *, processed_at: datetime | None
) -> uuid.UUID:
    event_id = uuid7()
    await admin.execute(
        "INSERT INTO public.outbox "
        "(id, organization_id, event_type, aggregate_type, aggregate_id, processed_at) "
        "VALUES ($1, $2, 'item.created', 'item', $3, $4)",
        event_id,
        org,
        uuid7(),
        processed_at,
    )
    return event_id


async def _seed_processed_event(
    admin: asyncpg.Connection[asyncpg.Record], org: uuid.UUID, *, processed_at: datetime
) -> uuid.UUID:
    row_id = uuid7()
    event_id = uuid7()
    await admin.execute(
        "INSERT INTO public.processed_events (id, organization_id, consumer_name, event_id, processed_at) "
        "VALUES ($1, $2, 'housekeeping-probe', $3, $4)",
        row_id,
        org,
        event_id,
        processed_at,
    )
    return event_id


async def test_old_rows_are_deleted_and_new_and_unprocessed_rows_are_kept(
    make_pool: PoolFactory, isolation_db: IsolationDb, admin: asyncpg.Connection[asyncpg.Record]
) -> None:
    with time_machine.travel("2026-02-01T00:00:00Z", tick=False):
        old_time = clock.now() - timedelta(days=8)
        recent_time = clock.now() - timedelta(days=1)
        old_outbox = await _seed_outbox(admin, isolation_db.org_a, processed_at=old_time)
        recent_outbox = await _seed_outbox(admin, isolation_db.org_a, processed_at=recent_time)
        unprocessed_outbox = await _seed_outbox(admin, isolation_db.org_a, processed_at=None)
        old_processed_event = await _seed_processed_event(admin, isolation_db.org_b, processed_at=old_time)
        recent_processed_event = await _seed_processed_event(
            admin, isolation_db.org_b, processed_at=recent_time
        )

        pool = await make_pool("worker")
        await run_once(pool, default_registry())

        assert await admin.fetchval("SELECT 1 FROM public.outbox WHERE id = $1", old_outbox) is None
        assert await admin.fetchval("SELECT 1 FROM public.outbox WHERE id = $1", recent_outbox) == 1
        assert await admin.fetchval("SELECT 1 FROM public.outbox WHERE id = $1", unprocessed_outbox) == 1
        assert (
            await admin.fetchval(
                "SELECT 1 FROM public.processed_events WHERE event_id = $1", old_processed_event
            )
            is None
        )
        assert (
            await admin.fetchval(
                "SELECT 1 FROM public.processed_events WHERE event_id = $1", recent_processed_event
            )
            == 1
        )

        # Running it again is a no-op: nothing left old enough to delete, no error either way.
        await run_once(pool, default_registry())
        assert await admin.fetchval("SELECT 1 FROM public.outbox WHERE id = $1", recent_outbox) == 1


async def test_two_organizations_are_each_cleaned_in_their_own_transaction(
    make_pool: PoolFactory, isolation_db: IsolationDb, admin: asyncpg.Connection[asyncpg.Record]
) -> None:
    with time_machine.travel("2026-02-01T00:00:00Z", tick=False):
        old_time = clock.now() - timedelta(days=8)
        org_a_old = await _seed_outbox(admin, isolation_db.org_a, processed_at=old_time)
        org_b_old = await _seed_outbox(admin, isolation_db.org_b, processed_at=old_time)
        pool = await make_pool("worker")

        await run_once(pool, default_registry())
        assert await admin.fetchval("SELECT 1 FROM public.outbox WHERE id = $1", org_a_old) is None
        assert await admin.fetchval("SELECT 1 FROM public.outbox WHERE id = $1", org_b_old) is None


def test_registering_the_same_task_name_twice_is_refused() -> None:
    registry = default_registry()

    async def noop(pool: object) -> None:
        return None

    registry.register_housekeeping_task("extra", noop)  # type: ignore[arg-type]
    assert registry.task_names() == ["extra"]
    with pytest.raises(ValueError, match="already registered"):
        registry.register_housekeeping_task("extra", noop)  # type: ignore[arg-type]


async def test_an_extra_task_runs_and_a_failing_one_does_not_stop_the_rest(
    make_pool: PoolFactory,
) -> None:
    pool = await make_pool("worker")
    ran: list[str] = []

    async def good(_pool: object) -> None:
        ran.append("good")

    async def bad(_pool: object) -> None:
        raise ValueError("boom")

    registry: HousekeepingRegistry = default_registry()
    registry.register_housekeeping_task("bad", bad)  # type: ignore[arg-type]
    registry.register_housekeeping_task("good", good)  # type: ignore[arg-type]
    await run_once(pool, registry)
    assert ran == ["good"]
