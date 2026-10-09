# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""`limit=0` must not crash a catalog list endpoint (PR #289 review, good-to-fix).

`len(rows) == limit` is `True` when both are `0`, and the next line indexed `rows[-1]` on an
empty list -- an `IndexError` (500) instead of an empty page. Covers the three call sites that
share this pattern: categories, custom field definitions, and the manufacturer/supplier
`_list_reference` helper.
"""

from __future__ import annotations

import uuid

from pg_harness import IsolationDb, PoolFactory

from app.core.scope import MemberContext, RoleGrant, ScopeType
from app.modules.assets.catalog.schemas import CategoryCreate, ManufacturerCreate
from app.modules.assets.catalog.service import (
    create_category,
    create_manufacturer,
    list_categories,
    list_custom_field_definitions,
    list_manufacturers,
)


def _caller(organization_id: uuid.UUID) -> MemberContext:
    return MemberContext(
        member_id=str(uuid.uuid4()),
        organization_id=str(organization_id),
        grants=(
            RoleGrant(
                id="g",
                organization_id=str(organization_id),
                role_key="admin",
                scope_type=ScopeType.ORGANIZATION,
            ),
        ),
    )


async def test_list_categories_with_limit_zero_returns_an_empty_page(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    pool = await make_pool("api")
    org = isolation_db.org_a
    caller = _caller(org)
    await create_category(
        pool, organization_id=org, caller=caller, data=CategoryCreate(code="cat-a", name="A")
    )

    page = await list_categories(pool, organization_id=org, caller=caller, limit=0)

    assert page.items == []
    assert page.next_cursor is None


async def test_list_custom_field_definitions_with_limit_zero_returns_an_empty_page(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    pool = await make_pool("api")
    org = isolation_db.org_b
    caller = _caller(org)
    category = await create_category(
        pool, organization_id=org, caller=caller, data=CategoryCreate(code="cat-b", name="B")
    )

    page = await list_custom_field_definitions(
        pool, organization_id=org, caller=caller, category_id=category.id, limit=0
    )

    assert page.items == []
    assert page.next_cursor is None


async def test_list_manufacturers_with_limit_zero_returns_an_empty_page(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    pool = await make_pool("api")
    org = isolation_db.org_a
    caller = _caller(org)
    await create_manufacturer(pool, organization_id=org, caller=caller, data=ManufacturerCreate(name="Acme"))

    page = await list_manufacturers(pool, organization_id=org, caller=caller, limit=0)

    assert page.items == []
    assert page.next_cursor is None
