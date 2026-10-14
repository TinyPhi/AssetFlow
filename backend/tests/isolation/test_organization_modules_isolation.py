# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Tenant isolation tests for organization_modules (§B5.2, §B8, §B10, §C4.8, §C8.5)."""

from __future__ import annotations

from pg_harness import IsolationDb, PoolFactory
from tenant_checks import assert_tenant_isolation


async def test_organization_modules_tenant_isolation(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    await assert_tenant_isolation(
        make_pool,
        isolation_db,
        "organization_modules",
        "INSERT INTO public.organization_modules (id, organization_id, module_key, template_key) "
        "VALUES ($1, $2, 'assets', $3)",
        update_column="status",
    )
