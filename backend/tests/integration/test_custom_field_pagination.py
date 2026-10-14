# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Custom-field-definition list pagination sorts `(position, key, id)` (PR #289 review, blocker 1).

A cursor built from only `(key, id)` silently drops rows: two definitions can share a key prefix
but sort at a different position, and the `(key, id) > (cursor_key, cursor_id)` predicate excludes
a later-position-but-earlier-key row that the query's own ORDER BY would have returned next.
"""

from __future__ import annotations

import uuid

from pg_harness import IsolationDb, PoolFactory

from app.core.db import tenant_transaction
from app.core.permissions import ScopeFilter
from app.modules.assets.catalog.repository import (
    CustomFieldDefinitionRepository,
    decode_field_cursor,
    encode_field_cursor,
)

INSERT_CATEGORY = (
    "INSERT INTO public.asset_categories (id, organization_id, parent_id, path, code, name) "
    "VALUES ($1, $2, NULL, $3::ltree, $3, $3)"
)


async def test_keyset_pagination_does_not_drop_a_row_with_a_lower_key_but_higher_position(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    pool = await make_pool("api")
    org = isolation_db.org_a
    category_id = uuid.uuid4()
    repo = CustomFieldDefinitionRepository()
    scope = ScopeFilter.all_organization()

    async with tenant_transaction(pool, org) as conn:
        await conn.execute(INSERT_CATEGORY, category_id, org, "field-paging")

        # Sorted by (position, key, id) this is: (1, "b"), (2, "a"), (2, "c").
        await repo.create(
            conn,
            field_id=uuid.uuid4(),
            organization_id=org,
            category_id=category_id,
            key="b",
            label="B",
            field_type="text",
            is_required=False,
            rules={},
            is_unique=False,
            is_encrypted=False,
            position=1,
        )
        await repo.create(
            conn,
            field_id=uuid.uuid4(),
            organization_id=org,
            category_id=category_id,
            key="a",
            label="A",
            field_type="text",
            is_required=False,
            rules={},
            is_unique=False,
            is_encrypted=False,
            position=2,
        )
        await repo.create(
            conn,
            field_id=uuid.uuid4(),
            organization_id=org,
            category_id=category_id,
            key="c",
            label="C",
            field_type="text",
            is_required=False,
            rules={},
            is_unique=False,
            is_encrypted=False,
            position=2,
        )

        seen: list[str] = []
        after: tuple[int, str, uuid.UUID] | None = None
        for _ in range(5):
            rows = await repo.list_by_category(
                conn,
                organization_id=org,
                scope_filter=scope,
                category_id=category_id,
                after=after,
                limit=1,
            )
            if not rows:
                break
            seen.append(rows[-1]["key"])
            after = (rows[-1]["position"], rows[-1]["key"], rows[-1]["id"])

    assert seen == ["b", "a", "c"]


def test_field_cursor_roundtrips_position_key_and_id() -> None:
    field_id = uuid.uuid4()
    cursor = encode_field_cursor(3, "some-key", field_id)
    assert decode_field_cursor(cursor) == (3, "some-key", field_id)
