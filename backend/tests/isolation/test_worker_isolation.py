# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The worker role stays inside the organization boundary (§B9.3, §C5.4 rule 3, §C8.5 last line)."""

from __future__ import annotations

import uuid

import asyncpg
import pytest
from pg_harness import IsolationDb, PoolFactory

from app.core.db import Connection, platform_transaction, worker_context
from app.core.ids import uuid7
from workers.outbox_dispatcher import DispatcherOptions, run_once
from workers.subscribers import OutboxEvent, SubscriberRegistry
from workers.sweep import for_each_active_organization

OPTIONS = DispatcherOptions(batch_size=10, reclaim_after_seconds=300, max_attempts=2)


async def _tenant_tables(conn: asyncpg.Connection[asyncpg.Record]) -> list[str]:
    rows = await conn.fetch(
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'organization_id' AND NOT a.attisdropped "
        "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') AND NOT c.relispartition "
        "ORDER BY c.relname"
    )
    return [row["relname"] for row in rows]


async def test_worker_without_context_reads_nothing_but_the_outbox_claim_columns(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    admin = await asyncpg.connect(isolation_db.admin_dsn)
    try:
        for org in (isolation_db.org_a, isolation_db.org_b):
            await admin.execute(
                "INSERT INTO public.processed_events (id, organization_id, consumer_name, event_id) "
                "VALUES ($1, $2, 'isolation-probe', $3)",
                uuid7(),
                org,
                uuid7(),
            )
            await admin.execute(
                "INSERT INTO public.audit_events (id, organization_id, action, entity_type, entity_id) "
                "VALUES ($1, $2, 'test.probe', 'event', $3)",
                uuid7(),
                org,
                uuid7(),
            )
        tables = await _tenant_tables(admin)
        assert {"processed_events", "audit_events", "outbox"} <= set(tables)
        worker = await make_pool("worker")
        for table in tables:
            if table == "outbox":
                continue  # the one table with a worker claim policy (§B9.3)
            async with platform_transaction(worker) as conn:
                try:
                    visible = await conn.fetchval(f"SELECT count(*) FROM public.{table}")  # noqa: S608
                except asyncpg.InsufficientPrivilegeError:
                    continue  # no grant at all is just as closed
            assert visible == 0, f"worker without a context can read {table}"
    finally:
        await admin.execute("DELETE FROM public.processed_events WHERE consumer_name = 'isolation-probe'")
        await admin.close()


async def test_list_active_organizations_is_for_the_worker_only(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    admin = await asyncpg.connect(isolation_db.admin_dsn)
    suspended = uuid.uuid4()
    try:
        await admin.execute(
            "INSERT INTO public.organizations (id, slug, name, idp_organization_id, domain_key, status) "
            "VALUES ($1, 'org-suspended', 'Suspended', 'idp-suspended', 'it', 'suspended')",
            suspended,
        )
        worker = await make_pool("worker")
        async with platform_transaction(worker) as conn:
            ids = [r[0] for r in await conn.fetch("SELECT * FROM platform.list_active_organizations()")]
        assert isolation_db.org_a in ids
        assert isolation_db.org_b in ids
        assert suspended not in ids

        api = await make_pool("api")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with platform_transaction(api) as conn:
                await conn.fetch("SELECT * FROM platform.list_active_organizations()")
        readonly = await make_pool("readonly")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with platform_transaction(readonly) as conn:
                await conn.fetch("SELECT * FROM platform.list_active_organizations()")
    finally:
        await admin.execute("DELETE FROM public.organizations WHERE id = $1", suspended)
        await admin.close()


async def test_subscriber_for_org_a_cannot_touch_org_b(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    admin = await asyncpg.connect(isolation_db.admin_dsn)
    await admin.execute("DELETE FROM public.outbox")
    other_event = uuid7()
    await admin.execute(
        "INSERT INTO public.processed_events (id, organization_id, consumer_name, event_id) "
        "VALUES ($1, $2, 'b-only', $3)",
        uuid7(),
        isolation_db.org_b,
        other_event,
    )
    event_id = uuid7()
    await admin.execute(
        "INSERT INTO public.outbox (id, organization_id, event_type, aggregate_type, aggregate_id) "
        "VALUES ($1, $2, 'item.created', 'item', $3)",
        event_id,
        isolation_db.org_a,
        uuid7(),
    )
    seen: dict[str, int] = {}

    async def reads_other_org(conn: Connection, event: OutboxEvent) -> None:
        seen["visible_b_rows"] = await conn.fetchval(
            "SELECT count(*) FROM public.processed_events WHERE organization_id = $1", isolation_db.org_b
        )
        # A write for organization B is refused by row-level security, so the event fails.
        await conn.execute(
            "INSERT INTO public.processed_events (id, organization_id, consumer_name, event_id) "
            "VALUES ($1, $2, 'cross', $3)",
            uuid7(),
            isolation_db.org_b,
            uuid7(),
        )

    registry = SubscriberRegistry()
    registry.subscribe("item.created", "cross-reader", reads_other_org)
    try:
        worker = await make_pool("worker")
        assert await run_once(worker, registry, "worker-1", OPTIONS) == 1
        assert seen["visible_b_rows"] == 0
        failed = await admin.fetchrow(
            "SELECT last_error, processed_at FROM public.outbox WHERE id = $1", event_id
        )
        assert failed is not None
        assert failed["last_error"] == "InsufficientPrivilegeError"
        assert failed["processed_at"] is None
        assert (
            await admin.fetchval("SELECT count(*) FROM public.processed_events WHERE consumer_name = 'cross'")
            == 0
        )
        # Same role, org B's own context: the row is there, so the boundary is the context, not the grant.
        async with worker_context(worker, isolation_db.org_b) as conn:
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM public.processed_events WHERE consumer_name = 'b-only'"
                )
                == 1
            )
    finally:
        await admin.execute("DELETE FROM public.outbox")
        await admin.execute(
            "DELETE FROM public.processed_events WHERE consumer_name IN ('b-only', 'cross-reader')"
        )
        await admin.close()


async def test_sweep_sets_the_context_and_without_it_reads_zero_rows(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    admin = await asyncpg.connect(isolation_db.admin_dsn)
    marker = uuid7()
    try:
        await admin.execute(
            "INSERT INTO public.processed_events (id, organization_id, consumer_name, event_id) "
            "VALUES ($1, $2, 'sweep-probe', $3)",
            uuid7(),
            isolation_db.org_a,
            marker,
        )
        worker = await make_pool("worker")
        seen: dict[uuid.UUID, int] = {}

        async def count_marker(conn: Connection, organization_id: uuid.UUID) -> None:
            seen[organization_id] = await conn.fetchval(
                "SELECT count(*) FROM public.processed_events WHERE event_id = $1", marker
            )

        await for_each_active_organization(worker, count_marker)
        assert seen[isolation_db.org_a] == 1
        assert seen[isolation_db.org_b] == 0  # the context was org_b's own, not org_a's row leaking

        # Without the sweep's per-organization context, the same query under no context sees nothing.
        async with platform_transaction(worker) as conn:
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM public.processed_events WHERE event_id = $1", marker
                )
                == 0
            )
    finally:
        await admin.execute("DELETE FROM public.processed_events WHERE consumer_name = 'sweep-probe'")
        await admin.close()
