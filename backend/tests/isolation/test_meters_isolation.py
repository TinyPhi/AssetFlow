# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Tenant isolation tests for meters (§B8.2, §B9.2, §C4.8, §C8.5)."""

from __future__ import annotations

import uuid

import asyncpg
import pytest
from pg_harness import IsolationDb, PoolFactory
from tenant_checks import token

from app.core.db import Pool, tenant_transaction

INSERT_CATEGORY = (
    "INSERT INTO public.asset_categories (id, organization_id, parent_id, path, code, name) "
    "VALUES ($1, $2, NULL, $3::ltree, $3, $3)"
)
INSERT_ORG_UNIT = (
    "INSERT INTO public.org_units (id, organization_id, parent_id, path, type, code, name) "
    "VALUES ($1, $2, NULL, $3::ltree, 'unit', $3, $3)"
)
INSERT_ASSET = (
    "INSERT INTO public.assets (id, organization_id, tag, name, category_id, owner_org_unit_id) "
    "VALUES ($1, $2, $3, $3, $4, $5)"
)
INSERT_METER = (
    "INSERT INTO public.meters (id, organization_id, asset_id, code, name, unit) "
    "VALUES ($1, $2, $3, $4, $4, 'hours')"
)


async def _make_asset(pool: Pool, org: uuid.UUID) -> uuid.UUID:
    category_id, unit_id, asset_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with tenant_transaction(pool, org) as conn:
        await conn.execute(INSERT_CATEGORY, category_id, org, token())
        await conn.execute(INSERT_ORG_UNIT, unit_id, org, token())
        await conn.execute(INSERT_ASSET, asset_id, org, token(), category_id, unit_id)
    return asset_id


async def test_meters_tenant_isolation(make_pool: PoolFactory, isolation_db: IsolationDb) -> None:
    pool = await make_pool("api")
    asset_a = await _make_asset(pool, isolation_db.org_a)
    asset_b = await _make_asset(pool, isolation_db.org_b)

    row_a, row_b = uuid.uuid4(), uuid.uuid4()
    async with tenant_transaction(pool, isolation_db.org_a) as conn:
        await conn.execute(INSERT_METER, row_a, isolation_db.org_a, asset_a, token())
    async with tenant_transaction(pool, isolation_db.org_b) as conn:
        await conn.execute(INSERT_METER, row_b, isolation_db.org_b, asset_b, token())

    select_sql = "SELECT id FROM public.meters WHERE id = ANY($1::uuid[])"
    ids = [row_a, row_b]
    async with tenant_transaction(pool, isolation_db.org_a) as conn:
        rows = await conn.fetch(select_sql, ids)
        assert [r["id"] for r in rows] == [row_a]
        assert await conn.execute("UPDATE public.meters SET name = name WHERE id = $1", row_a) == "UPDATE 1"
        with pytest.raises(asyncpg.InsufficientPrivilegeError, match="permission denied"):
            async with conn.transaction():
                await conn.execute("DELETE FROM public.meters WHERE id = $1", row_a)
        with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
            await conn.execute(INSERT_METER, uuid.uuid4(), isolation_db.org_b, asset_b, token())


async def test_meter_asset_must_be_in_the_same_organization(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    pool = await make_pool("api")
    asset_a = await _make_asset(pool, isolation_db.org_a)
    async with tenant_transaction(pool, isolation_db.org_b) as conn:
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await conn.execute(INSERT_METER, uuid.uuid4(), isolation_db.org_b, asset_a, token())
