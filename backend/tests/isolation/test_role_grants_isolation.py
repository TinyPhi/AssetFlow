# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Tenant isolation tests for role_grants (§B5.2, §B10, §C4.8, §C8.5)."""

from __future__ import annotations

from pg_harness import IsolationDb, PoolFactory
from tenant_checks import assert_tenant_isolation

# The member is created in the same statement and organization.
INSERT = """
WITH m AS (
    INSERT INTO public.members (id, organization_id, idp_subject, email, display_name)
    VALUES (gen_random_uuid(), $2, $3, $3 || '@example.test', $3) RETURNING id
)
INSERT INTO public.role_grants (id, organization_id, member_id, role_key, scope_type, source)
SELECT $1, $2, m.id, 'admin', 'organization', 'manual' FROM m
"""


async def test_role_grants_tenant_isolation(make_pool: PoolFactory, isolation_db: IsolationDb) -> None:
    await assert_tenant_isolation(make_pool, isolation_db, "role_grants", INSERT, update_column="role_key")
