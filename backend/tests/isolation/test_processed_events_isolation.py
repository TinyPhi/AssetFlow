# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Tenant isolation tests for processed_events, written by the worker (§B9.3, §B10, §C4.8)."""

from __future__ import annotations

from pg_harness import IsolationDb, PoolFactory
from tenant_checks import assert_tenant_isolation


async def test_processed_events_tenant_isolation(make_pool: PoolFactory, isolation_db: IsolationDb) -> None:
    await assert_tenant_isolation(
        make_pool,
        isolation_db,
        "processed_events",
        "INSERT INTO public.processed_events (id, organization_id, consumer_name, event_id) "
        "VALUES ($1, $2, $3, gen_random_uuid())",
        update_column="consumer_name",
        role="worker",
        can_update=False,
    )
