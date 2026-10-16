# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Tenant isolation tests for asset_categories (§B8.1, §B8.2, §C4.8, §C8.5)."""

from __future__ import annotations

import uuid

import asyncpg
import pytest
from pg_harness import IsolationDb, PoolFactory
from tenant_checks import assert_tenant_isolation, token

from app.core.db import tenant_transaction

INSERT_ROOT = (
    "INSERT INTO public.asset_categories (id, organization_id, parent_id, path, code, name) "
    "VALUES ($1, $2, NULL, $3::ltree, $3, $3)"
)


async def test_asset_categories_tenant_isolation(make_pool: PoolFactory, isolation_db: IsolationDb) -> None:
    # Categories are archived by status, never deleted: the api role has no DELETE grant (§B14.1).
    await assert_tenant_isolation(make_pool, isolation_db, "asset_categories", INSERT_ROOT, can_delete=False)


async def test_asset_category_parent_must_be_in_the_same_organization(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    root_a, _ = await assert_tenant_isolation(
        make_pool, isolation_db, "asset_categories", INSERT_ROOT, can_delete=False
    )
    pool = await make_pool("api")
    async with tenant_transaction(pool, isolation_db.org_b) as conn:
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await conn.execute(
                "INSERT INTO public.asset_categories (id, organization_id, parent_id, path, code, name) "
                "VALUES ($1, $2, $3, $4::ltree, $4, $4)",
                uuid.uuid4(),
                isolation_db.org_b,
                root_a,
                token(),
            )
