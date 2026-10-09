# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Tenant isolation tests for v_asset_inventory (§B8.1, §B8.2, §C1.4, §C4.8, §C8.5)."""

from __future__ import annotations

import uuid

from pg_harness import IsolationDb, PoolFactory
from tenant_checks import token

from app.core.db import Pool, platform_transaction, tenant_transaction

INSERT_CATEGORY = (
    "INSERT INTO public.asset_categories (id, organization_id, parent_id, path, code, name) "
    "VALUES ($1, $2, NULL, $3::ltree, $3, $3)"
)
INSERT_ORG_UNIT = (
    "INSERT INTO public.org_units (id, organization_id, parent_id, path, type, code, name) "
    "VALUES ($1, $2, NULL, $3::ltree, 'unit', $3, $3)"
)
INSERT_MEMBER = (
    "INSERT INTO public.members (id, organization_id, idp_subject, email, display_name) "
    "VALUES ($1, $2, $3, $3 || '@example.test', $3)"
)
INSERT_ASSET = (
    "INSERT INTO public.assets "
    "(id, organization_id, tag, name, category_id, owner_org_unit_id, holder_member_id, "
    "encrypted_fields) "
    'VALUES ($1, $2, $3, $3, $4, $5, $6, \'{"serial_number": "secret"}\'::jsonb)'
)


async def _make_asset_with_holder(pool: Pool, org: uuid.UUID) -> tuple[uuid.UUID, str, uuid.UUID]:
    category_id, unit_id, member_id, asset_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    member_name = token()
    async with tenant_transaction(pool, org) as conn:
        await conn.execute(INSERT_CATEGORY, category_id, org, token())
        await conn.execute(INSERT_ORG_UNIT, unit_id, org, token())
        await conn.execute(INSERT_MEMBER, member_id, org, member_name)
        await conn.execute(INSERT_ASSET, asset_id, org, token(), category_id, unit_id, member_id)
    return asset_id, member_name, member_id


async def test_v_asset_inventory_tenant_isolation(make_pool: PoolFactory, isolation_db: IsolationDb) -> None:
    pool = await make_pool("api")
    asset_a, holder_name_a, member_id_a = await _make_asset_with_holder(pool, isolation_db.org_a)
    asset_b, _, _ = await _make_asset_with_holder(pool, isolation_db.org_b)

    select_sql = "SELECT * FROM public.v_asset_inventory WHERE id = ANY($1::uuid[])"
    ids = [asset_a, asset_b]
    async with platform_transaction(pool) as conn:
        assert await conn.fetch(select_sql, ids) == []

    async with tenant_transaction(pool, isolation_db.org_a) as conn:
        rows = await conn.fetch(select_sql, ids)
        assert [r["id"] for r in rows] == [asset_a]
        row = rows[0]
        assert "encrypted_fields" not in row
        assert row["holder_type"] == "member"
        assert row["holder_id"] == member_id_a
        assert row["holder_display_name"] == holder_name_a
        assert row["category_name"] is not None
        assert row["owner_org_unit_name"] is not None


async def test_v_asset_inventory_readonly_role_can_select(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    api_pool = await make_pool("api")
    asset_a, _, _ = await _make_asset_with_holder(api_pool, isolation_db.org_a)

    readonly_pool = await make_pool("readonly")
    async with tenant_transaction(readonly_pool, isolation_db.org_a) as conn:
        rows = await conn.fetch("SELECT id FROM public.v_asset_inventory WHERE id = $1", asset_a)
        assert [r["id"] for r in rows] == [asset_a]
