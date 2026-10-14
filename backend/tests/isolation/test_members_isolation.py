# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Tenant isolation tests for members (§B5.2, §B10, §C4.8, §C8.5)."""

from __future__ import annotations

from pg_harness import IsolationDb, PoolFactory
from tenant_checks import assert_tenant_isolation


async def test_members_tenant_isolation(make_pool: PoolFactory, isolation_db: IsolationDb) -> None:
    await assert_tenant_isolation(
        make_pool,
        isolation_db,
        "members",
        "INSERT INTO public.members (id, organization_id, idp_subject, email, display_name) "
        "VALUES ($1, $2, $3, $3 || '@example.test', $3)",
        update_column="display_name",
    )
