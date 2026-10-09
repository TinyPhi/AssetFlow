# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Tenant isolation tests for the notification delivery log (§B6.3, §C8.5)."""

from __future__ import annotations

import uuid

import asyncpg
import pytest
from pg_harness import IsolationDb, PoolFactory
from tenant_checks import token

from app.core.db import Pool, platform_transaction, tenant_transaction


async def _insert_channel(pool: Pool, organization_id: uuid.UUID) -> uuid.UUID:
    channel_id = uuid.uuid4()
    async with tenant_transaction(pool, organization_id) as conn:
        await conn.execute(
            "INSERT INTO public.notification_channels (id, organization_id, channel_key, display_name) "
            "VALUES ($1, $2, $3, 'Test channel')",
            channel_id,
            organization_id,
            token(),
        )
    return channel_id


def _insert_delivery_sql() -> str:
    return (
        "INSERT INTO public.notification_deliveries "
        "(id, organization_id, channel_id, channel_key, event_id, target, idempotency_key) "
        "VALUES ($1, $2, $3, 'inapp', $4, 'member:test', $5)"
    )


async def test_notification_deliveries_worker_tenant_isolation(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    worker = await make_pool("worker")
    api = await make_pool("api")  # only the api role may create channel installations
    channel_a = await _insert_channel(api, isolation_db.org_a)
    channel_b = await _insert_channel(api, isolation_db.org_b)
    row_a, row_b = uuid.uuid4(), uuid.uuid4()
    insert = _insert_delivery_sql()
    async with tenant_transaction(worker, isolation_db.org_a) as conn:
        await conn.execute(insert, row_a, isolation_db.org_a, channel_a, uuid.uuid4(), token())
    async with tenant_transaction(worker, isolation_db.org_b) as conn:
        await conn.execute(insert, row_b, isolation_db.org_b, channel_b, uuid.uuid4(), token())

    async with platform_transaction(worker) as conn:
        assert (
            await conn.fetch(
                "SELECT id FROM public.notification_deliveries WHERE id = ANY($1::uuid[])",
                [row_a, row_b],
            )
            == []
        )

    async with tenant_transaction(worker, isolation_db.org_a) as conn:
        rows = await conn.fetch(
            "SELECT id FROM public.notification_deliveries WHERE id = ANY($1::uuid[])", [row_a, row_b]
        )
        assert [r["id"] for r in rows] == [row_a]
        assert (
            await conn.execute(
                "UPDATE public.notification_deliveries SET status = 'sent' WHERE id = $1", row_a
            )
            == "UPDATE 1"
        )
        assert (
            await conn.execute(
                "UPDATE public.notification_deliveries SET status = 'sent' WHERE id = $1", row_b
            )
            == "UPDATE 0"
        )
        with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
            await conn.execute(insert, uuid.uuid4(), isolation_db.org_b, channel_b, uuid.uuid4(), token())


async def test_api_can_read_and_requeue_but_not_create_or_rewrite_deliveries(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    worker = await make_pool("worker")
    api = await make_pool("api")  # only the api role may create channel installations
    channel_a = await _insert_channel(api, isolation_db.org_a)
    row_id = uuid.uuid4()
    insert = _insert_delivery_sql()
    async with tenant_transaction(worker, isolation_db.org_a) as conn:
        await conn.execute(insert, row_id, isolation_db.org_a, channel_a, uuid.uuid4(), token())

    async with tenant_transaction(api, isolation_db.org_a) as conn:
        found = await conn.fetchval("SELECT status FROM public.notification_deliveries WHERE id = $1", row_id)
        assert found == "pending"
        # P6-06c (0014): the api role may reset a delivery's retry state (re-queue a dead letter)
        # - those columns only, never who or what it was for.
        await conn.execute(
            "UPDATE public.notification_deliveries SET status = 'pending', attempts = 0 WHERE id = $1", row_id
        )
        with pytest.raises(asyncpg.InsufficientPrivilegeError, match="permission denied"):
            async with conn.transaction():
                await conn.execute(
                    "UPDATE public.notification_deliveries SET target = 'x' WHERE id = $1", row_id
                )
        with pytest.raises(asyncpg.InsufficientPrivilegeError, match="permission denied"):
            async with conn.transaction():
                await conn.execute(insert, uuid.uuid4(), isolation_db.org_a, channel_a, uuid.uuid4(), token())
