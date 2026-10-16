# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The `inapp` channel and `dispatch.enqueue`, against a real PostgreSQL (§B6.3, M1.5-T3)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import asyncpg
import pytest
from pg_harness import IsolationDb, PoolFactory
from tenant_checks import token

from app.core.db import Pool, tenant_transaction
from app.engines.automation.planner import NotificationIntent
from app.modules.notifications.dispatch import enqueue


def _intent(organization_id: uuid.UUID, member_id: uuid.UUID, event_id: uuid.UUID) -> NotificationIntent:
    return NotificationIntent(
        event_id=event_id,
        organization_id=organization_id,
        member_id=member_id,
        channel_key="inapp",
        template_key="team-member-added",
        idempotency_key=f"test-{event_id}-{member_id}-inapp",
        event_type="team_member.added",
        event_data={"team_id": str(uuid.uuid4()), "member_id": str(member_id), "team_role": "member"},
    )


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


@pytest.fixture
async def admin(isolation_db: IsolationDb) -> AsyncIterator[asyncpg.Connection[asyncpg.Record]]:
    conn = await asyncpg.connect(isolation_db.admin_dsn)
    yield conn
    await conn.execute("DELETE FROM public.notification_deliveries")
    await conn.execute("DELETE FROM public.notifications")
    await conn.close()


async def test_sending_the_same_intent_twice_writes_one_notice_and_one_delivery(
    make_pool: PoolFactory, isolation_db: IsolationDb, admin: asyncpg.Connection[asyncpg.Record]
) -> None:
    worker = await make_pool("worker")
    member_id = await _insert_member(await make_pool("api"), isolation_db.org_a)
    event_id = uuid.uuid4()
    intent = _intent(isolation_db.org_a, member_id, event_id)

    async with tenant_transaction(worker, isolation_db.org_a) as conn:
        await enqueue(conn, [intent])
    async with tenant_transaction(worker, isolation_db.org_a) as conn:
        await enqueue(conn, [intent])  # the exact same intent again

    assert (
        await admin.fetchval(
            "SELECT count(*) FROM public.notifications WHERE idempotency_key = $1", intent.idempotency_key
        )
        == 1
    )
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM public.notification_deliveries WHERE idempotency_key = $1",
            intent.idempotency_key,
        )
        == 1
    )
    delivery = await admin.fetchrow(
        "SELECT status, channel_key, recipient_member_id FROM public.notification_deliveries "
        "WHERE idempotency_key = $1",
        intent.idempotency_key,
    )
    assert delivery is not None
    assert delivery["status"] == "sent"
    assert delivery["channel_key"] == "inapp"
    assert delivery["recipient_member_id"] == member_id


async def test_the_notice_body_is_rendered_from_the_template(
    make_pool: PoolFactory, isolation_db: IsolationDb, admin: asyncpg.Connection[asyncpg.Record]
) -> None:
    worker = await make_pool("worker")
    member_id = await _insert_member(await make_pool("api"), isolation_db.org_a)
    intent = _intent(isolation_db.org_a, member_id, uuid.uuid4())

    async with tenant_transaction(worker, isolation_db.org_a) as conn:
        await enqueue(conn, [intent])

    body = await admin.fetchval(
        "SELECT body FROM public.notifications WHERE idempotency_key = $1", intent.idempotency_key
    )
    assert "member" in body  # the team_role value from event_data, rendered into the html template


async def test_an_external_channel_intent_is_recorded_pending_not_sent(
    make_pool: PoolFactory, isolation_db: IsolationDb, admin: asyncpg.Connection[asyncpg.Record]
) -> None:
    worker = await make_pool("worker")
    member_id = await _insert_member(await make_pool("api"), isolation_db.org_a)
    event_id = uuid.uuid4()
    await admin.execute(
        "INSERT INTO public.notification_channels (id, organization_id, channel_key, display_name) "
        "VALUES ($1, $2, 'email', 'Email')",
        uuid.uuid4(),
        isolation_db.org_a,
    )
    intent = NotificationIntent(
        event_id=event_id,
        organization_id=isolation_db.org_a,
        member_id=member_id,
        channel_key="email",
        template_key="team-member-added",
        idempotency_key=f"test-{event_id}-{member_id}-email",
        event_type="team_member.added",
        event_data={"team_role": "member"},
    )
    async with tenant_transaction(worker, isolation_db.org_a) as conn:
        await enqueue(conn, [intent])

    status = await admin.fetchval(
        "SELECT status FROM public.notification_deliveries WHERE idempotency_key = $1",
        intent.idempotency_key,
    )
    assert status == "pending"
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM public.notifications WHERE idempotency_key = $1", intent.idempotency_key
        )
        == 0
    )  # email never writes to the in-app inbox
