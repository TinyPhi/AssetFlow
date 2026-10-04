# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Tenant isolation tests for custom_field_definitions (§B8.1, §B8.2, §C4.8, §C8.5)."""

from __future__ import annotations

import uuid

import asyncpg
import pytest
from pg_harness import IsolationDb, PoolFactory
from tenant_checks import token

from app.core.db import Pool, platform_transaction, tenant_transaction

INSERT_CATEGORY = (
    "INSERT INTO public.asset_categories (id, organization_id, parent_id, path, code, name) "
    "VALUES ($1, $2, NULL, $3::ltree, $3, $3)"
)
INSERT_FIELD = (
    "INSERT INTO public.custom_field_definitions "
    "(id, organization_id, category_id, key, label, field_type) "
    "VALUES ($1, $2, $3, $4, $4, 'text')"
)


async def _make_category(pool: Pool, org: uuid.UUID) -> uuid.UUID:
    category_id = uuid.uuid4()
    async with tenant_transaction(pool, org) as conn:
        await conn.execute(INSERT_CATEGORY, category_id, org, token())
    return category_id


async def test_custom_field_definitions_tenant_isolation(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    # assert_tenant_isolation's insert_sql takes only $1 (id), $2 (organization_id), $3 (a token),
    # but a field definition also needs a category_id that itself must belong to the organization,
    # so the rows for A and B are created by hand here instead of through the shared helper.
    pool = await make_pool("api")
    category_a = await _make_category(pool, isolation_db.org_a)
    category_b = await _make_category(pool, isolation_db.org_b)

    row_a, row_b = uuid.uuid4(), uuid.uuid4()
    async with tenant_transaction(pool, isolation_db.org_a) as conn:
        await conn.execute(INSERT_FIELD, row_a, isolation_db.org_a, category_a, token())
    async with tenant_transaction(pool, isolation_db.org_b) as conn:
        await conn.execute(INSERT_FIELD, row_b, isolation_db.org_b, category_b, token())

    select_sql = "SELECT id FROM public.custom_field_definitions WHERE id = ANY($1::uuid[])"
    ids = [row_a, row_b]
    async with platform_transaction(pool) as conn:
        assert await conn.fetch(select_sql, ids) == []

    async with tenant_transaction(pool, isolation_db.org_a) as conn:
        rows = await conn.fetch(select_sql, ids)
        assert [r["id"] for r in rows] == [row_a]
        # No DELETE grant for the api role (archived by status, §B14.1).
        with pytest.raises(asyncpg.InsufficientPrivilegeError, match="permission denied"):
            async with conn.transaction():
                await conn.execute("DELETE FROM public.custom_field_definitions WHERE id = $1", row_a)
        with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
            await conn.execute(INSERT_FIELD, uuid.uuid4(), isolation_db.org_b, category_b, token())


async def test_custom_field_definition_category_must_be_in_the_same_organization(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    pool = await make_pool("api")
    category_a = await _make_category(pool, isolation_db.org_a)
    async with tenant_transaction(pool, isolation_db.org_b) as conn:
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await conn.execute(INSERT_FIELD, uuid.uuid4(), isolation_db.org_b, category_a, token())
