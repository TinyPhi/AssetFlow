# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Tenant isolation tests for the outbox (§B9.3, §B10, §C4.8, §C8.5)."""

from __future__ import annotations

from pg_harness import IsolationDb, PoolFactory
from tenant_checks import assert_tenant_isolation

from app.core.db import platform_transaction

INSERT = (
    "INSERT INTO public.outbox (id, organization_id, event_type, aggregate_type, aggregate_id) "
    "VALUES ($1, $2, $3, 'item', gen_random_uuid())"
)


async def test_outbox_api_tenant_isolation(make_pool: PoolFactory, isolation_db: IsolationDb) -> None:
    # The API only appends events; claiming and cleanup belong to the worker.
    await assert_tenant_isolation(
        make_pool,
        isolation_db,
        "outbox",
        INSERT,
        update_column="event_type",
        can_update=False,
        can_delete=False,
    )


async def test_worker_claim_policy_reaches_across_organizations(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    """Master plan §B9.3: the worker process claims outbox events across organizations."""
    msg_a, _ = await assert_tenant_isolation(
        make_pool,
        isolation_db,
        "outbox",
        INSERT,
        update_column="event_type",
        can_update=False,
        can_delete=False,
    )
    worker_pool = await make_pool("worker")
    async with platform_transaction(worker_pool) as conn:
        row = await conn.fetchrow(
            "UPDATE public.outbox SET claimed_by = 'worker-1', claimed_at = now() "
            "WHERE id = $1 AND claimed_by IS NULL RETURNING id, organization_id",
            msg_a,
        )
    assert row is not None
    assert row["id"] == msg_a
    assert row["organization_id"] == isolation_db.org_a
