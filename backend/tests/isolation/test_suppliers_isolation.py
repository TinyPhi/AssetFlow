# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Tenant isolation tests for suppliers (§B8.1, §B8.2, §C4.8, §C8.5)."""

from __future__ import annotations

from pg_harness import IsolationDb, PoolFactory
from tenant_checks import assert_tenant_isolation


async def test_suppliers_tenant_isolation(make_pool: PoolFactory, isolation_db: IsolationDb) -> None:
    # Archived by status, never deleted: the api role has no DELETE grant (§B14.1).
    await assert_tenant_isolation(
        make_pool,
        isolation_db,
        "suppliers",
        "INSERT INTO public.suppliers (id, organization_id, name) VALUES ($1, $2, $3)",
        can_delete=False,
    )
