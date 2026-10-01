# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Tenant isolation tests for audit_events, insert-only for application roles (§B10, §C4.8, §C8.5)."""

from __future__ import annotations

import pytest
from pg_harness import IsolationDb, PoolFactory
from tenant_checks import assert_tenant_isolation

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
