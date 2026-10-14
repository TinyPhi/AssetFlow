# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Audit store isolation: personal values, partitions, and scoped read API (§B5.3, §B10, §1590, §2138)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import asyncpg
import pytest
from pg_harness import IsolationDb, PoolFactory
from tenant_checks import assert_tenant_isolation

from app.core.db import platform_transaction, tenant_transaction
from app.modules.audit.housekeeping import check_partition_health, maintain_partitions


async def test_audit_personal_values_tenant_isolation(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    ev_id = uuid4()
    ins = (
        "INSERT INTO public.audit_personal_values (id, organization_id, audit_event_id, "  # noqa: S608
        f"field_name, field_value) VALUES ($1, $2, '{ev_id}'::uuid, 'email', $3)"
    )
    await assert_tenant_isolation(
        make_pool,
        isolation_db,
        table="audit_personal_values",
        insert_sql=ins,
        update_column="field_value",
        can_update=False,
        can_delete=True,
    )
    api_pool, worker_pool = await make_pool("api"), await make_pool("worker")
    row_id = uuid4()
    ins_pv = "INSERT INTO public.audit_personal_values VALUES ($1, $2, $3, 'name', 'Alice', now())"
    async with tenant_transaction(api_pool, isolation_db.org_a) as conn:
        await conn.execute(ins_pv, row_id, isolation_db.org_a, ev_id)
    async with tenant_transaction(worker_pool, isolation_db.org_a) as conn:
        assert (
            await conn.execute("DELETE FROM public.audit_personal_values WHERE id = $1", row_id) == "DELETE 1"
        )


async def test_audit_partitioning_housekeeping_and_routing(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    api_pool, worker_pool, migrator_pool = (
        await make_pool("api"),
        await make_pool("worker"),
        await make_pool("migrator"),
    )
    async with platform_transaction(worker_pool) as conn:
        await maintain_partitions(conn, base_date=datetime.now(UTC), months_ahead=3)

    fut, ev_early = datetime(2030, 5, 15, 12, 0, 0, tzinfo=UTC), uuid4()
    ins_ev = (
        "INSERT INTO public.audit_events (id, organization_id, action, entity_type, entity_id, created_at) "
        "VALUES ($1, $2, 'test', 'item', $3, $4)"
    )
    sel_tbl = "SELECT tableoid::regclass::text FROM public.audit_events WHERE id = $1"
    async with tenant_transaction(api_pool, isolation_db.org_a) as conn:
        await conn.execute(ins_ev, ev_early, isolation_db.org_a, uuid4(), fut)
        assert await conn.fetchval(sel_tbl, ev_early) == "audit_events_default"

    async with platform_transaction(worker_pool) as conn:
        h1 = await check_partition_health(conn, base_date=fut)
        assert h1["alert"] is True and h1["default_rows"] >= 1
        created = await maintain_partitions(conn, base_date=fut, months_ahead=2)
        assert "audit_events_2030_05" in created
        h2 = await check_partition_health(conn, base_date=fut)
        assert h2["alert"] is False and h2["default_rows"] == 0

    ev_late = uuid4()
    async with tenant_transaction(api_pool, isolation_db.org_a) as conn:
        assert await conn.fetchval(sel_tbl, ev_early) == "audit_events_2030_05"
        await conn.execute(ins_ev, ev_late, isolation_db.org_a, uuid4(), fut)
        assert await conn.fetchval(sel_tbl, ev_late) == "audit_events_2030_05"
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.fetch("SELECT * FROM public.audit_events_2030_05")
    async with tenant_transaction(api_pool, isolation_db.org_a) as conn:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.fetch("SELECT * FROM public.audit_events_default")

    async with platform_transaction(migrator_pool) as conn:
        chk = (
            "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class "
            "WHERE oid = 'public.audit_events_2030_05'::regclass"
        )
        assert await conn.fetchval(chk) is True
