# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Cross-organization foreign keys on the notification tables (§B6.3, §C8.5).

Every foreign key here is composite (`organization_id`, `<id>`) against the referenced table's own
`UNIQUE (organization_id, id)`, so a row from another organization is not just invisible under
row-level security - there is no matching key for it to reference at all.
"""

from __future__ import annotations

import uuid

import asyncpg
import pytest
from pg_harness import IsolationDb, PoolFactory
from tenant_checks import token

from app.core.db import Pool, tenant_transaction


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


async def test_a_notification_for_org_b_member_cannot_be_inserted_as_org_a(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    api = await make_pool("api")
    member_b = await _insert_member(api, isolation_db.org_b)
    async with tenant_transaction(api, isolation_db.org_a) as conn:
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await conn.execute(
                "INSERT INTO public.notifications "
                "(id, organization_id, member_id, event_type, event_id, template_key, title_key, "
                "body, idempotency_key) "
                "VALUES ($1, $2, $3, 'item.created', $4, 'item_created', 'item_created.title', "
                "'body', $5)",
                uuid.uuid4(),
                isolation_db.org_a,
                member_b,  # org_b's member id, but the row claims to be org_a's
                uuid.uuid4(),
                token(),
            )


async def test_a_preference_for_org_b_member_cannot_be_inserted_as_org_a(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    api = await make_pool("api")
    member_b = await _insert_member(api, isolation_db.org_b)
    async with tenant_transaction(api, isolation_db.org_a) as conn:
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await conn.execute(
                "INSERT INTO public.notification_preferences "
                "(id, organization_id, member_id, event_type, channel_key) "
                "VALUES ($1, $2, $3, 'item.created', 'email')",
                uuid.uuid4(),
                isolation_db.org_a,
                member_b,
            )


async def test_a_delivery_for_org_b_channel_cannot_be_inserted_as_org_a(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    worker = await make_pool("worker")
    api = await make_pool("api")  # only the api role may create channel installations
    channel_b = await _insert_channel(api, isolation_db.org_b)
    async with tenant_transaction(worker, isolation_db.org_a) as conn:
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await conn.execute(
                "INSERT INTO public.notification_deliveries "
                "(id, organization_id, channel_id, channel_key, event_id, target, idempotency_key) "
                "VALUES ($1, $2, $3, 'inapp', $4, 'member:test', $5)",
                uuid.uuid4(),
                isolation_db.org_a,
                channel_b,
                uuid.uuid4(),
                token(),
            )
