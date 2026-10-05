# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Tenant isolation tests for asset_saved_views (§B8.1, §C4.8, §C8.5, P8-07)."""

from __future__ import annotations

import uuid

from pg_harness import IsolationDb, PoolFactory
from tenant_checks import assert_tenant_isolation, token

from app.core.db import Pool, tenant_transaction

# $1 id, $2 organization_id, $3 token; the owning member is picked by a subquery scoped to the same
# organization (the statement runs inside tenant_transaction for org_a and org_b in turn).
INSERT = (
    "INSERT INTO public.asset_saved_views (id, organization_id, member_id, name) "
    "VALUES ($1, $2, (SELECT id FROM public.members WHERE organization_id = $2 LIMIT 1), $3)"
)


async def _insert_member(pool: Pool, organization_id: uuid.UUID) -> None:
    async with tenant_transaction(pool, organization_id) as conn:
        await conn.execute(
            "INSERT INTO public.members (id, organization_id, idp_subject, email, display_name) "
            "VALUES ($1, $2, $3, $4, 'Test Member')",
            uuid.uuid4(),
            organization_id,
            f"idp-{token()}",
            f"{token()}@example.org",
        )


async def test_asset_saved_views_tenant_isolation(make_pool: PoolFactory, isolation_db: IsolationDb) -> None:
    api = await make_pool("api")
    await _insert_member(api, isolation_db.org_a)
    await _insert_member(api, isolation_db.org_b)
    await assert_tenant_isolation(make_pool, isolation_db, "asset_saved_views", INSERT)
