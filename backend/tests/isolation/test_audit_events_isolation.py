# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Tenant isolation tests for audit_events, insert-only for application roles (§B10, §C4.8, §C8.5)."""

from __future__ import annotations

import asyncpg
import pytest
from pg_harness import IsolationDb, PoolFactory
from tenant_checks import assert_tenant_isolation

from app.core.db import tenant_transaction

INSERT = (
    "INSERT INTO public.audit_events (id, organization_id, action, entity_type, entity_id) "
    "VALUES ($1, $2, $3, 'org_unit', gen_random_uuid())"
)


@pytest.mark.parametrize("role", ["api", "worker"])
async def test_audit_events_are_isolated_and_insert_only(
    make_pool: PoolFactory, isolation_db: IsolationDb, role: str
) -> None:
    await assert_tenant_isolation(
        make_pool,
        isolation_db,
        "audit_events",
        INSERT,
        update_column="action",
        role=role,
        can_update=False,
        can_delete=False,
    )


async def test_audit_events_are_partitioned_by_month_without_a_member_foreign_key(
    isolation_db: IsolationDb,
) -> None:
    conn = await asyncpg.connect(isolation_db.admin_dsn)
    try:
        strategy = await conn.fetchval(
            "SELECT partstrat::text FROM pg_partitioned_table "
            "WHERE partrelid = 'public.audit_events'::regclass"
        )
        default = await conn.fetchval(
            "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class "
            "WHERE oid = 'public.audit_events_default'::regclass"
        )
        member_fks = await conn.fetchval(
            "SELECT count(*) FROM pg_constraint WHERE contype = 'f' "
            "AND conrelid = 'public.audit_events'::regclass AND confrelid = 'public.members'::regclass"
        )
    finally:
        await conn.close()
    assert strategy == "r"  # range partitions on created_at
    assert default is True  # the DEFAULT partition is fail-closed on direct access
    assert member_fks == 0  # deleting a member must never rewrite audit rows


async def test_audit_partition_cannot_be_read_directly(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    pool = await make_pool("api")
    async with tenant_transaction(pool, isolation_db.org_a) as conn:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.fetch("SELECT * FROM public.audit_events_default")
