# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Tenant isolation tests for teams (§B5.2, §B10, §C4.8, §C8.5)."""

from __future__ import annotations

from pg_harness import IsolationDb, PoolFactory
from tenant_checks import assert_tenant_isolation


async def test_teams_tenant_isolation(make_pool: PoolFactory, isolation_db: IsolationDb) -> None:
    await assert_tenant_isolation(
        make_pool,
        isolation_db,
        "teams",
        "INSERT INTO public.teams (id, organization_id, code, name, type) VALUES ($1, $2, $3, $3, 'core')",
    )
