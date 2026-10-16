# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Asset tag generation against a real PostgreSQL (master M2.1-T3, §B7.3, §B8.1, M1.3-T3).

Runs against the isolation suite's real database (`pg_harness`, re-exported by
`tests/integration/conftest.py`). `isolation_db.org_a` / `org_b` are shared by the whole test
session (not reset between tests), so every test here uses its own freshly generated tag prefix
(`_unique_prefix`): `organization_sequences` counts per `(organization_id, prefix)`, so a fresh
prefix always starts this test's own counter at 1 regardless of what other tests already did in
the same organization. The concurrency proof below runs 50 real, concurrent writer transactions
against the same organization, the same prefix and the same connection pool - never mocked -
because a row-lock race is exactly the kind of bug a mock cannot reproduce.
"""

from __future__ import annotations

import asyncio
import secrets
import uuid

import pytest
from pg_harness import IsolationDb, PoolFactory

from app.core.db import Pool, tenant_transaction
from app.modules.assets.config import TagConfig
from app.modules.assets.errors import TagConflictError
from app.modules.assets.tags import assign_tag, next_tag, validate_supplied_tag

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


def _token() -> str:
    return "t" + uuid.uuid4().hex[:12]


def _unique_prefix() -> str:
    """A fresh tag prefix, so this test's `organization_sequences` counter always starts at 1."""
    return "P" + secrets.token_hex(4).upper()


def _tag_config(prefix: str) -> TagConfig:
    return TagConfig(prefix=prefix, separator="-", digits=5)


async def _make_category_and_unit(pool: Pool, org: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    category_id, unit_id = uuid.uuid4(), uuid.uuid4()
    async with tenant_transaction(pool, org) as conn:
        await conn.execute(INSERT_CATEGORY, category_id, org, _token())
        await conn.execute(INSERT_ORG_UNIT, unit_id, org, _token())
    return category_id, unit_id


async def _create_asset_with_a_generated_tag(
    pool: Pool, org: uuid.UUID, tag_config: TagConfig, category_id: uuid.UUID, unit_id: uuid.UUID
) -> str:
    async with tenant_transaction(pool, org) as conn:
        tag = await assign_tag(conn, org, tag_config)
        await conn.execute(INSERT_ASSET, uuid.uuid4(), org, tag, category_id, unit_id)
    return tag


async def test_sequence_starts_at_one_and_increments(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    pool = await make_pool("api")
    prefix = _unique_prefix()
    async with tenant_transaction(pool, isolation_db.org_a) as conn:
        first = await next_tag(conn, isolation_db.org_a, prefix)
        second = await next_tag(conn, isolation_db.org_a, prefix)
    assert (first, second) == (1, 2)


async def test_distinct_prefixes_count_on_their_own(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    pool = await make_pool("api")
    prefix_a, prefix_b = _unique_prefix(), _unique_prefix()
    async with tenant_transaction(pool, isolation_db.org_a) as conn:
        a_1 = await next_tag(conn, isolation_db.org_a, prefix_a)
        b_1 = await next_tag(conn, isolation_db.org_a, prefix_b)
        a_2 = await next_tag(conn, isolation_db.org_a, prefix_a)
    assert (a_1, b_1, a_2) == (1, 1, 2)


async def test_two_organizations_each_start_at_one_and_never_collide(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    pool = await make_pool("api")
    prefix = _unique_prefix()
    async with tenant_transaction(pool, isolation_db.org_a) as conn:
        a_1 = await next_tag(conn, isolation_db.org_a, prefix)
        a_2 = await next_tag(conn, isolation_db.org_a, prefix)
    async with tenant_transaction(pool, isolation_db.org_b) as conn:
        b_1 = await next_tag(conn, isolation_db.org_b, prefix)
    assert (a_1, a_2, b_1) == (1, 2, 1)


async def test_fifty_concurrent_creates_in_one_organization_give_fifty_distinct_tags(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    pool = await make_pool("api")
    tag_config = _tag_config(_unique_prefix())
    category_id, unit_id = await _make_category_and_unit(pool, isolation_db.org_a)

    tags = await asyncio.gather(
        *(
            _create_asset_with_a_generated_tag(pool, isolation_db.org_a, tag_config, category_id, unit_id)
            for _ in range(50)
        )
    )

    assert len(tags) == 50
    assert len(set(tags)) == 50
    async with tenant_transaction(pool, isolation_db.org_a) as conn:
        count = await conn.fetchval(
            "SELECT count(*) FROM public.assets WHERE organization_id = $1 AND tag = ANY($2::text[])",
            isolation_db.org_a,
            tags,
        )
    assert count == 50


async def test_supplied_duplicate_tag_is_refused(make_pool: PoolFactory, isolation_db: IsolationDb) -> None:
    pool = await make_pool("api")
    tag_config = _tag_config(_unique_prefix())
    category_id, unit_id = await _make_category_and_unit(pool, isolation_db.org_a)
    existing = await _create_asset_with_a_generated_tag(
        pool, isolation_db.org_a, tag_config, category_id, unit_id
    )

    async with tenant_transaction(pool, isolation_db.org_a) as conn:
        with pytest.raises(TagConflictError):
            await validate_supplied_tag(conn, isolation_db.org_a, tag_config, None, existing)


async def test_supplied_tag_unique_in_organization_is_not_checked_across_organizations(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    pool = await make_pool("api")
    tag_config = _tag_config(_unique_prefix())
    category_a, unit_a = await _make_category_and_unit(pool, isolation_db.org_a)
    shared_tag = await _create_asset_with_a_generated_tag(
        pool, isolation_db.org_a, tag_config, category_a, unit_a
    )

    await _make_category_and_unit(pool, isolation_db.org_b)
    async with tenant_transaction(pool, isolation_db.org_b) as conn:
        # RLS scopes the uniqueness SELECT to org_b, so org_a's tag is not a conflict here.
        await validate_supplied_tag(conn, isolation_db.org_b, tag_config, None, shared_tag)


async def test_a_rolled_back_create_does_not_reuse_a_committed_tag(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    """A rolled-back create's own number may be reused (the increment rolls back with it - no
    permanent gap, since both the counter and the insert are in the one transaction); what must
    never happen is reusing a number that an earlier, *committed* create already turned into a tag.
    """
    pool = await make_pool("api")
    tag_config = _tag_config(_unique_prefix())
    category_id, unit_id = await _make_category_and_unit(pool, isolation_db.org_a)
    first_tag = await _create_asset_with_a_generated_tag(
        pool, isolation_db.org_a, tag_config, category_id, unit_id
    )

    with pytest.raises(RuntimeError):
        async with tenant_transaction(pool, isolation_db.org_a) as conn:
            second_tag = await assign_tag(conn, isolation_db.org_a, tag_config)
            assert second_tag != first_tag
            await conn.execute(
                INSERT_ASSET, uuid.uuid4(), isolation_db.org_a, second_tag, category_id, unit_id
            )
            # Simulate the rest of the asset-create transaction failing after the tag was assigned
            # and the row was written, so the rollback has something real to undo.
            raise RuntimeError("boom")

    # The next successful create gets a number that was never attached to a committed asset.
    third_tag = await _create_asset_with_a_generated_tag(
        pool, isolation_db.org_a, tag_config, category_id, unit_id
    )
    assert third_tag != first_tag
    async with tenant_transaction(pool, isolation_db.org_a) as conn:
        rows = await conn.fetch(
            "SELECT tag FROM public.assets WHERE organization_id = $1 AND category_id = $2",
            isolation_db.org_a,
            category_id,
        )
    tags = {row["tag"] for row in rows}
    assert tags == {first_tag, third_tag}  # the rolled-back create's row never landed
    assert len(tags) == 2  # and whichever number it reused, the two committed tags are distinct
