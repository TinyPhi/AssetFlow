# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Tenant isolation tests for locations (§B5.2, §B10, §C4.8, §C8.5)."""

from __future__ import annotations

import uuid

import asyncpg
import pytest
from pg_harness import IsolationDb, PoolFactory
from tenant_checks import assert_tenant_isolation, token

from app.core.db import tenant_transaction

INSERT_ROOT = (
    "INSERT INTO public.locations (id, organization_id, parent_id, path, type, code, name) "
    "VALUES ($1, $2, NULL, $3::ltree, 'site', $3, $3)"
)


async def test_locations_tenant_isolation(make_pool: PoolFactory, isolation_db: IsolationDb) -> None:
    await assert_tenant_isolation(make_pool, isolation_db, "locations", INSERT_ROOT)


async def test_location_parent_must_be_in_the_same_organization(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    site_a, _ = await assert_tenant_isolation(make_pool, isolation_db, "locations", INSERT_ROOT)
    pool = await make_pool("api")
    async with tenant_transaction(pool, isolation_db.org_b) as conn:
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await conn.execute(
                "INSERT INTO public.locations (id, organization_id, parent_id, path, type, code, name) "
                "VALUES ($1, $2, $3, $4::ltree, 'room', $4, $4)",
                uuid.uuid4(),
                isolation_db.org_b,
                site_a,
                token(),
            )
