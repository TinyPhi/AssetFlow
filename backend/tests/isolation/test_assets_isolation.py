# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Tenant isolation tests for assets (§B5.3, §B8.2, §C4.8, §C8.5)."""

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
INSERT_ORG_UNIT = (
    "INSERT INTO public.org_units (id, organization_id, parent_id, path, type, code, name) "
    "VALUES ($1, $2, $3, $4::ltree, 'unit', $5, $5)"
)
INSERT_MEMBER = (
    "INSERT INTO public.members (id, organization_id, idp_subject, email, display_name) "
    "VALUES ($1, $2, $3, $3 || '@example.test', $3)"
)
INSERT_TEAM = (
    "INSERT INTO public.teams (id, organization_id, code, name, type) VALUES ($1, $2, $3, $3, 'crew')"
)
INSERT_LOCATION = (
    "INSERT INTO public.locations (id, organization_id, parent_id, path, type, code, name) "
    "VALUES ($1, $2, NULL, $3::ltree, 'site', $3, $3)"
)
INSERT_ASSET = (
    "INSERT INTO public.assets (id, organization_id, tag, name, category_id, owner_org_unit_id) "
    "VALUES ($1, $2, $3, $3, $4, $5)"
)


async def _make_category(pool: Pool, org: uuid.UUID) -> uuid.UUID:
    category_id = uuid.uuid4()
    async with tenant_transaction(pool, org) as conn:
        await conn.execute(INSERT_CATEGORY, category_id, org, token())
    return category_id


async def _make_org_unit(
    pool: Pool, org: uuid.UUID, parent_id: uuid.UUID | None = None, path: str | None = None
) -> tuple[uuid.UUID, str]:
    unit_id = uuid.uuid4()
    unit_path = path or token()
    async with tenant_transaction(pool, org) as conn:
        await conn.execute(INSERT_ORG_UNIT, unit_id, org, parent_id, unit_path, token())
    return unit_id, unit_path


async def _make_member(pool: Pool, org: uuid.UUID) -> uuid.UUID:
    member_id = uuid.uuid4()
    async with tenant_transaction(pool, org) as conn:
        await conn.execute(INSERT_MEMBER, member_id, org, token())
    return member_id


async def _make_team(pool: Pool, org: uuid.UUID) -> uuid.UUID:
    team_id = uuid.uuid4()
    async with tenant_transaction(pool, org) as conn:
        await conn.execute(INSERT_TEAM, team_id, org, token())
    return team_id


async def _make_location(pool: Pool, org: uuid.UUID) -> uuid.UUID:
    location_id = uuid.uuid4()
    async with tenant_transaction(pool, org) as conn:
        await conn.execute(INSERT_LOCATION, location_id, org, token())
    return location_id


async def test_assets_tenant_isolation(make_pool: PoolFactory, isolation_db: IsolationDb) -> None:
    # assert_tenant_isolation's insert_sql takes only id/organization_id/token, but an asset also
    # needs a category and an owner org unit that themselves belong to the organization, so the
    # rows for A and B are created by hand here instead of through the shared helper.
    pool = await make_pool("api")
    category_a = await _make_category(pool, isolation_db.org_a)
    category_b = await _make_category(pool, isolation_db.org_b)
    unit_a, _ = await _make_org_unit(pool, isolation_db.org_a)
    unit_b, _ = await _make_org_unit(pool, isolation_db.org_b)

    row_a, row_b = uuid.uuid4(), uuid.uuid4()
    async with tenant_transaction(pool, isolation_db.org_a) as conn:
        await conn.execute(INSERT_ASSET, row_a, isolation_db.org_a, token(), category_a, unit_a)
    async with tenant_transaction(pool, isolation_db.org_b) as conn:
        await conn.execute(INSERT_ASSET, row_b, isolation_db.org_b, token(), category_b, unit_b)

    select_sql = "SELECT id FROM public.assets WHERE id = ANY($1::uuid[])"
    ids = [row_a, row_b]
    async with platform_transaction(pool) as conn:
        assert await conn.fetch(select_sql, ids) == []

    async with tenant_transaction(pool, isolation_db.org_a) as conn:
        rows = await conn.fetch(select_sql, ids)
        assert [r["id"] for r in rows] == [row_a]
        # api holds UPDATE (status changes, custody) but no DELETE (archived by status, §B14.1).
        assert await conn.execute("UPDATE public.assets SET name = name WHERE id = $1", row_a) == "UPDATE 1"
        with pytest.raises(asyncpg.InsufficientPrivilegeError, match="permission denied"):
            async with conn.transaction():
                await conn.execute("DELETE FROM public.assets WHERE id = $1", row_a)
        # The owner_org_unit_path BEFORE trigger (SECURITY INVOKER) looks up org_units under the
        # *current session's* organization context before the INSERT's own RLS check is reached,
        # so a cross-organization attempt fails closed there first, as "no data found" rather than
        # a row-level-security error - still refused, just a step earlier in the pipeline.
        with pytest.raises(asyncpg.NoDataFoundError):
            await conn.execute(INSERT_ASSET, uuid.uuid4(), isolation_db.org_b, token(), category_b, unit_b)


async def test_asset_category_must_be_in_the_same_organization(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    pool = await make_pool("api")
    category_a = await _make_category(pool, isolation_db.org_a)
    unit_b, _ = await _make_org_unit(pool, isolation_db.org_b)
    async with tenant_transaction(pool, isolation_db.org_b) as conn:
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await conn.execute(INSERT_ASSET, uuid.uuid4(), isolation_db.org_b, token(), category_a, unit_b)


async def test_asset_owner_org_unit_must_be_in_the_same_organization(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    # The composite FK (organization_id, owner_org_unit_id) would refuse this too, but the
    # owner_org_unit_path BEFORE trigger's own RLS-scoped lookup of org_units fails closed first
    # ("no data found": unit_a is invisible under org_b's context), before the FK check is reached.
    pool = await make_pool("api")
    category_b = await _make_category(pool, isolation_db.org_b)
    unit_a, _ = await _make_org_unit(pool, isolation_db.org_a)
    async with tenant_transaction(pool, isolation_db.org_b) as conn:
        with pytest.raises(asyncpg.NoDataFoundError):
            await conn.execute(INSERT_ASSET, uuid.uuid4(), isolation_db.org_b, token(), category_b, unit_a)


async def test_asset_holder_location_must_be_in_the_same_organization(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    pool = await make_pool("api")
    category_b = await _make_category(pool, isolation_db.org_b)
    unit_b, _ = await _make_org_unit(pool, isolation_db.org_b)
    location_a = await _make_location(pool, isolation_db.org_a)
    async with tenant_transaction(pool, isolation_db.org_b) as conn:
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await conn.execute(
                "INSERT INTO public.assets "
                "(id, organization_id, tag, name, category_id, owner_org_unit_id, holder_location_id) "
                "VALUES ($1, $2, $3, $3, $4, $5, $6)",
                uuid.uuid4(),
                isolation_db.org_b,
                token(),
                category_b,
                unit_b,
                location_a,
            )


async def test_asset_holder_member_must_be_in_the_same_organization(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    pool = await make_pool("api")
    category_b = await _make_category(pool, isolation_db.org_b)
    unit_b, _ = await _make_org_unit(pool, isolation_db.org_b)
    member_a = await _make_member(pool, isolation_db.org_a)
    async with tenant_transaction(pool, isolation_db.org_b) as conn:
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await conn.execute(
                "INSERT INTO public.assets "
                "(id, organization_id, tag, name, category_id, owner_org_unit_id, holder_member_id) "
                "VALUES ($1, $2, $3, $3, $4, $5, $6)",
                uuid.uuid4(),
                isolation_db.org_b,
                token(),
                category_b,
                unit_b,
                member_a,
            )


async def test_asset_holder_team_must_be_in_the_same_organization(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    pool = await make_pool("api")
    category_b = await _make_category(pool, isolation_db.org_b)
    unit_b, _ = await _make_org_unit(pool, isolation_db.org_b)
    team_a = await _make_team(pool, isolation_db.org_a)
    async with tenant_transaction(pool, isolation_db.org_b) as conn:
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await conn.execute(
                "INSERT INTO public.assets "
                "(id, organization_id, tag, name, category_id, owner_org_unit_id, holder_team_id) "
                "VALUES ($1, $2, $3, $3, $4, $5, $6)",
                uuid.uuid4(),
                isolation_db.org_b,
                token(),
                category_b,
                unit_b,
                team_a,
            )


async def test_asset_one_holder_check_refuses_two_holders(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    pool = await make_pool("api")
    category_a = await _make_category(pool, isolation_db.org_a)
    unit_a, _ = await _make_org_unit(pool, isolation_db.org_a)
    member_a = await _make_member(pool, isolation_db.org_a)
    team_a = await _make_team(pool, isolation_db.org_a)
    async with tenant_transaction(pool, isolation_db.org_a) as conn:
        with pytest.raises(asyncpg.CheckViolationError, match="ck_assets__one_holder"):
            await conn.execute(
                "INSERT INTO public.assets "
                "(id, organization_id, tag, name, category_id, owner_org_unit_id, "
                "holder_member_id, holder_team_id) "
                "VALUES ($1, $2, $3, $3, $4, $5, $6, $7)",
                uuid.uuid4(),
                isolation_db.org_a,
                token(),
                category_a,
                unit_a,
                member_a,
                team_a,
            )


async def test_asset_owner_org_unit_path_copied_on_insert(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    pool = await make_pool("api")
    category_a = await _make_category(pool, isolation_db.org_a)
    unit_a, unit_path = await _make_org_unit(pool, isolation_db.org_a)
    asset_id = uuid.uuid4()
    async with tenant_transaction(pool, isolation_db.org_a) as conn:
        await conn.execute(INSERT_ASSET, asset_id, isolation_db.org_a, token(), category_a, unit_a)
        row = await conn.fetchrow(
            "SELECT owner_org_unit_path::text AS path FROM public.assets WHERE id = $1", asset_id
        )
    assert row is not None
    assert row["path"] == unit_path


async def test_org_unit_move_rewrites_owner_org_unit_path_of_its_assets_only(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    """Moving an org unit (P5-04's two-step subtree rewrite) must cascade to its assets' cached
    path and must not touch assets owned elsewhere (§B8.2, plan P8-03 step 8)."""
    pool = await make_pool("api")
    category_a = await _make_category(pool, isolation_db.org_a)
    org = isolation_db.org_a

    root_id, root_path = await _make_org_unit(pool, org)
    child_id, child_path = await _make_org_unit(pool, org, parent_id=root_id, path=f"{root_path}.{token()}")
    other_id, other_path = await _make_org_unit(pool, org)

    asset_on_child = uuid.uuid4()
    asset_elsewhere = uuid.uuid4()
    async with tenant_transaction(pool, org) as conn:
        await conn.execute(INSERT_ASSET, asset_on_child, org, token(), category_a, child_id)
        await conn.execute(INSERT_ASSET, asset_elsewhere, org, token(), category_a, other_id)

    new_root_path = token()
    async with tenant_transaction(pool, org) as conn:
        # Mirrors app/modules/organization/repository.py's move_org_unit: cascade descendants
        # first (by the node's own old path), then move the node itself.
        await conn.execute(
            "UPDATE public.org_units "
            "SET path = $1::ltree || subpath(path, nlevel($2::ltree)), updated_at = now() "
            "WHERE organization_id = $3 AND path <@ $2::ltree AND id != $4",
            new_root_path,
            root_path,
            org,
            root_id,
        )
        await conn.execute(
            "UPDATE public.org_units SET path = $1::ltree, updated_at = now() "
            "WHERE organization_id = $2 AND id = $3",
            new_root_path,
            org,
            root_id,
        )
        child_row = await conn.fetchrow(
            "SELECT owner_org_unit_path::text AS path FROM public.assets WHERE id = $1", asset_on_child
        )
        other_row = await conn.fetchrow(
            "SELECT owner_org_unit_path::text AS path FROM public.assets WHERE id = $1", asset_elsewhere
        )

    assert child_row is not None and other_row is not None
    assert child_row["path"] == f"{new_root_path}.{child_path.rsplit('.', 1)[-1]}"
    assert other_row["path"] == other_path
