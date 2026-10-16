# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Archiving a category must not race a concurrent child-create or asset-assign (PR #289 blocker 2).

`CustomFieldDefinitionRepository.lock_active_children` / `lock_assets_using` take a real row lock
(`FOR UPDATE SKIP LOCKED`) on the children/assets that exist right now, so a concurrent transaction
that tries to UPDATE one of those same rows (reassigning an asset onto the category being archived,
say) must wait for the archiving transaction to finish, rather than slipping in between a `count(*)`
and the archive `UPDATE`.
"""

from __future__ import annotations

import asyncio
import uuid

from pg_harness import IsolationDb, PoolFactory

from app.core.db import tenant_transaction
from app.modules.assets.catalog.repository import CategoryRepository

INSERT_CATEGORY = (
    "INSERT INTO public.asset_categories (id, organization_id, parent_id, path, code, name) "
    "VALUES ($1, $2, NULL, $3::ltree, $3, $3)"
)
INSERT_ORG_UNIT = (
    "INSERT INTO public.org_units (id, organization_id, parent_id, path, type, code, name) "
    "VALUES ($1, $2, NULL, $3::ltree, 'unit', $3, $3)"
)
INSERT_ASSET = (
    "INSERT INTO public.assets "
    "(id, organization_id, tag, name, category_id, owner_org_unit_id) "
    "VALUES ($1, $2, $3, $3, $4, $5)"
)


async def test_locking_assets_using_a_category_blocks_a_concurrent_update_of_the_same_asset(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    pool = await make_pool("api")
    org = isolation_db.org_a
    category_id, org_unit_id, asset_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    async with tenant_transaction(pool, org) as conn:
        await conn.execute(INSERT_CATEGORY, category_id, org, "toctou-cat")
        await conn.execute(INSERT_ORG_UNIT, org_unit_id, org, "toctou-unit")
        await conn.execute(INSERT_ASSET, asset_id, org, "toctou-asset", category_id, org_unit_id)

    repo = CategoryRepository()
    order: list[str] = []

    async def archiving_transaction() -> None:
        async with tenant_transaction(pool, org) as conn:
            locked = await repo.lock_assets_using(conn, organization_id=org, category_id=category_id)
            assert locked == [asset_id]
            # Hold the row lock open for a bit so the concurrent update below has to wait for it.
            await asyncio.sleep(0.3)
            order.append("archive_released")

    async def concurrent_asset_update() -> None:
        async with tenant_transaction(pool, org) as conn:
            await conn.execute(
                "UPDATE public.assets SET name = $1 WHERE organization_id = $2 AND id = $3",
                "renamed-mid-archive",
                org,
                asset_id,
            )
            order.append("concurrent_update_committed")

    archiver = asyncio.create_task(archiving_transaction())
    await asyncio.sleep(0.05)  # let the archiver acquire its lock first
    updater = asyncio.create_task(concurrent_asset_update())

    await asyncio.wait_for(asyncio.gather(archiver, updater), timeout=5)

    # The concurrent UPDATE could only commit after the archiving transaction released its lock.
    assert order == ["archive_released", "concurrent_update_committed"]
