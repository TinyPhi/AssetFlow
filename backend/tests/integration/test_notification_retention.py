# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""In-app notice retention, against a real PostgreSQL (§B13.5, M1.5-T3)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta

import asyncpg
import pytest
import time_machine
from pg_harness import IsolationDb, PoolFactory
from tenant_checks import token

from app.core import clock
from app.core.db import Pool, tenant_transaction
from app.modules.notifications import retention

RETENTION_DAYS = 180


@pytest.fixture
async def admin(isolation_db: IsolationDb) -> AsyncIterator[asyncpg.Connection[asyncpg.Record]]:
    conn = await asyncpg.connect(isolation_db.admin_dsn)
    yield conn
    await conn.execute("DELETE FROM public.notifications")
    await conn.close()


async def _insert_member(pool: Pool, organization_id: uuid.UUID) -> uuid.UUID:
    member_id = uuid.uuid4()
    async with tenant_transaction(pool, organization_id) as conn:
        await conn.execute(
            "INSERT INTO public.members (id, organization_id, idp_subject, email, display_name, status) "
            "VALUES ($1, $2, $3, $4, 'Test Member', 'active')",
            member_id,
            organization_id,
            f"idp-{token()}",
            f"{token()}@example.org",
        )
    return member_id


async def _insert_notification(
    admin: asyncpg.Connection[asyncpg.Record],
    organization_id: uuid.UUID,
    member_id: uuid.UUID,
    created_at: datetime,
) -> uuid.UUID:
    row_id = uuid.uuid4()
    await admin.execute(
        "INSERT INTO public.notifications "
        "(id, organization_id, member_id, event_type, event_id, template_key, title_key, body, "
        "idempotency_key, created_at, updated_at) "
        "VALUES ($1, $2, $3, 'item.created', $4, 'x', 'x', 'x', $5, $6, $6)",
        row_id,
        organization_id,
        member_id,
        uuid.uuid4(),
        token(),
        created_at,
    )
    return row_id


async def test_old_notices_are_deleted_and_newer_ones_are_kept(
    make_pool: PoolFactory, isolation_db: IsolationDb, admin: asyncpg.Connection[asyncpg.Record]
) -> None:
    api = await make_pool("api")
    member_id = await _insert_member(api, isolation_db.org_a)

    with time_machine.travel("2026-03-01T00:00:00Z", tick=False):
        old_time = clock.now() - timedelta(days=RETENTION_DAYS + 1)
        recent_time = clock.now() - timedelta(days=RETENTION_DAYS - 1)
        old_id = await _insert_notification(admin, isolation_db.org_a, member_id, old_time)
        recent_id = await _insert_notification(admin, isolation_db.org_a, member_id, recent_time)

        worker = await make_pool("worker")
        await retention.run(worker, retention_days=RETENTION_DAYS)

        assert await admin.fetchval("SELECT 1 FROM public.notifications WHERE id = $1", old_id) is None
        assert await admin.fetchval("SELECT 1 FROM public.notifications WHERE id = $1", recent_id) == 1

        # Running it again is a no-op: nothing new old enough to delete.
        await retention.run(worker, retention_days=RETENTION_DAYS)
        assert await admin.fetchval("SELECT 1 FROM public.notifications WHERE id = $1", recent_id) == 1


async def test_each_organization_is_swept_in_its_own_context(
    make_pool: PoolFactory, isolation_db: IsolationDb, admin: asyncpg.Connection[asyncpg.Record]
) -> None:
    """One organization's old notice is deleted; a sibling organization's recent one is untouched -
    proving the sweep (one organization's context per transaction) does not cross organizations."""
    api = await make_pool("api")
    member_a = await _insert_member(api, isolation_db.org_a)
    member_b = await _insert_member(api, isolation_db.org_b)

    with time_machine.travel("2026-03-01T00:00:00Z", tick=False):
        old_time = clock.now() - timedelta(days=RETENTION_DAYS + 1)
        recent_time = clock.now() - timedelta(days=1)
        old_in_a = await _insert_notification(admin, isolation_db.org_a, member_a, old_time)
        recent_in_b = await _insert_notification(admin, isolation_db.org_b, member_b, recent_time)

        worker = await make_pool("worker")
        await retention.run(worker, retention_days=RETENTION_DAYS)

        assert await admin.fetchval("SELECT 1 FROM public.notifications WHERE id = $1", old_in_a) is None
        assert await admin.fetchval("SELECT 1 FROM public.notifications WHERE id = $1", recent_in_b) == 1
