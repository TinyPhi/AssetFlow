# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Tenant isolation tests for the in-app notification inbox (§B6.3, §C8.5)."""

from __future__ import annotations

import uuid

import asyncpg
import pytest
from pg_harness import IsolationDb, PoolFactory
from tenant_checks import token

from app.core.db import Pool, platform_transaction, tenant_transaction


async def _insert_member(pool: Pool, organization_id: uuid.UUID) -> uuid.UUID:
    member_id = uuid.uuid4()
    async with tenant_transaction(pool, organization_id) as conn:
        await conn.execute(
            "INSERT INTO public.members (id, organization_id, idp_subject, email, display_name) "
            "VALUES ($1, $2, $3, $4, 'Test Member')",
            member_id,
            organization_id,
            f"idp-{token()}",
            f"{token()}@example.org",
        )
    return member_id


def _insert_notification_sql() -> str:
    return (
        "INSERT INTO public.notifications "
        "(id, organization_id, member_id, event_type, event_id, template_key, title_key, body, "
        "idempotency_key) "
        "VALUES ($1, $2, $3, 'item.created', $4, 'item_created', 'item_created.title', 'body', $5)"
    )


async def test_notifications_api_tenant_isolation(make_pool: PoolFactory, isolation_db: IsolationDb) -> None:
    api = await make_pool("api")
    member_a = await _insert_member(api, isolation_db.org_a)
    member_b = await _insert_member(api, isolation_db.org_b)
    row_a, row_b = uuid.uuid4(), uuid.uuid4()
    insert = _insert_notification_sql()
    async with tenant_transaction(api, isolation_db.org_a) as conn:
        await conn.execute(insert, row_a, isolation_db.org_a, member_a, uuid.uuid4(), token())
    async with tenant_transaction(api, isolation_db.org_b) as conn:
        await conn.execute(insert, row_b, isolation_db.org_b, member_b, uuid.uuid4(), token())

    async with platform_transaction(api) as conn:
        assert (
            await conn.fetch("SELECT id FROM public.notifications WHERE id = ANY($1::uuid[])", [row_a, row_b])
            == []
        )

    async with tenant_transaction(api, isolation_db.org_a) as conn:
        rows = await conn.fetch(
            "SELECT id FROM public.notifications WHERE id = ANY($1::uuid[])", [row_a, row_b]
        )
        assert [r["id"] for r in rows] == [row_a]
        # Read state (mark read) is allowed on the api's own organization's row.
        assert (
            await conn.execute("UPDATE public.notifications SET read_at = now() WHERE id = $1", row_a)
            == "UPDATE 1"
        )
        assert await conn.execute("UPDATE public.notifications SET read_at = now() WHERE id = $1", row_b) == (
            "UPDATE 0"
        )
        with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
            await conn.execute(insert, uuid.uuid4(), isolation_db.org_b, member_b, uuid.uuid4(), token())


async def test_worker_can_write_and_delete_for_retention(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    worker = await make_pool("worker")
    api = await make_pool("api")  # only the api role may create members
    member_a = await _insert_member(api, isolation_db.org_a)
    row_id = uuid.uuid4()
    insert = _insert_notification_sql()
    async with tenant_transaction(worker, isolation_db.org_a) as conn:
        await conn.execute(insert, row_id, isolation_db.org_a, member_a, uuid.uuid4(), token())
        assert await conn.fetchval("SELECT count(*) FROM public.notifications WHERE id = $1", row_id) == 1
        assert await conn.execute("DELETE FROM public.notifications WHERE id = $1", row_id) == "DELETE 1"
