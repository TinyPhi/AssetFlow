# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Tenant isolation tests for working_calendars (§B5.2, §B10, §C4.8, §C8.5)."""

from __future__ import annotations

from pg_harness import IsolationDb, PoolFactory
from tenant_checks import assert_tenant_isolation


async def test_working_calendars_tenant_isolation(make_pool: PoolFactory, isolation_db: IsolationDb) -> None:
    await assert_tenant_isolation(
        make_pool,
        isolation_db,
        "working_calendars",
        "INSERT INTO public.working_calendars (id, organization_id, name, timezone, weekly_hours) "
        """VALUES ($1, $2, $3, 'UTC', '{"monday": [9, 17]}'::jsonb)""",
    )
