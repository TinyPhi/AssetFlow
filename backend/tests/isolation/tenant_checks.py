# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Shared tenant-isolation assertions for tenant tables (§B10, §C4.8, §C8.5).

Every tenant table gets the same proof: without an organization context nothing is visible, and in
organization A's context only A's rows are visible, B's rows cannot be updated or deleted, and a row
for B cannot be inserted.
"""

from __future__ import annotations

import re
import uuid

import asyncpg
import pytest
from pg_harness import IsolationDb, PoolFactory

from app.core.db import platform_transaction, tenant_transaction

IDENTIFIER = re.compile(r"[a-z][a-z0-9_]*")


def token() -> str:
    """A unique value that is also a valid ltree label, for codes, names and paths."""
    return "t" + uuid.uuid4().hex[:12]


async def assert_tenant_isolation(
    make_pool: PoolFactory,
    db: IsolationDb,
    table: str,
    insert_sql: str,
    update_column: str = "name",
    *,
    role: str = "api",
    can_update: bool = True,
    can_delete: bool = True,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Prove row-level isolation for `table`; returns the ids of the rows created for A and B.

    `insert_sql` takes $1 = id, $2 = organization_id and $3 = a unique token (see `token`).
    `role` is the login that writes the table; `can_update` / `can_delete` say whether it holds
    those privileges (without them the statement must fail before row-level security applies).
    """
    for name in (table, update_column):
        if not IDENTIFIER.fullmatch(name):
            raise ValueError(f"not a plain identifier: {name!r}")
    pool = await make_pool(role)
    row_a, row_b = uuid.uuid4(), uuid.uuid4()
    for row, org in ((row_a, db.org_a), (row_b, db.org_b)):
        async with tenant_transaction(pool, org) as conn:
            await conn.execute(insert_sql, row, org, token())

    # table and update_column are checked against IDENTIFIER above; values are always parameters.
    select_sql = f"SELECT id FROM public.{table} WHERE id = ANY($1::uuid[])"  # noqa: S608
    update_sql = f"UPDATE public.{table} SET {update_column} = {update_column} WHERE id = $1"  # noqa: S608
    delete_sql = f"DELETE FROM public.{table} WHERE id = $1"  # noqa: S608
    ids = [row_a, row_b]
    async with platform_transaction(pool) as conn:
        assert await conn.fetch(select_sql, ids) == []

    async with tenant_transaction(pool, db.org_a) as conn:
        rows = await conn.fetch(select_sql, ids)
        assert [r["id"] for r in rows] == [row_a]
        for sql, allowed, done in (
            (update_sql, can_update, "UPDATE 0"),
            (delete_sql, can_delete, "DELETE 0"),
        ):
            if allowed:
                assert await conn.execute(sql, row_b) == done
            else:
                with pytest.raises(asyncpg.InsufficientPrivilegeError, match="permission denied"):
                    async with conn.transaction():
                        await conn.execute(sql, row_a)
        with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
            await conn.execute(insert_sql, uuid.uuid4(), db.org_b, token())
    return row_a, row_b
