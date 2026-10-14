# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Tenant isolation tests for organization_sequences (M1.3-T3, §B7.3, §C4.8, §C8.5)."""

from __future__ import annotations

from pg_harness import IsolationDb, PoolFactory
from tenant_checks import assert_tenant_isolation

INSERT = (
    "INSERT INTO public.organization_sequences (id, organization_id, sequence_key, next_value) "
    "VALUES ($1, $2, 'test:' || $3, 1)"
)


async def test_organization_sequences_tenant_isolation(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    # A counter is never deleted by the application: the api role has no DELETE grant (§B14.1).
    await assert_tenant_isolation(
        make_pool,
        isolation_db,
        "organization_sequences",
        INSERT,
        update_column="sequence_key",
        can_delete=False,
    )
