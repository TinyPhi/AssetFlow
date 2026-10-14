# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Tenant isolation tests for member_org_units (§B5.2, §B10, §C4.8, §C8.5)."""

from __future__ import annotations

from pg_harness import IsolationDb, PoolFactory
from tenant_checks import assert_tenant_isolation

# The member and the org unit are created in the same statement and organization.
INSERT = """
WITH m AS (
    INSERT INTO public.members (id, organization_id, idp_subject, email, display_name)
    VALUES (gen_random_uuid(), $2, $3, $3 || '@example.test', $3) RETURNING id
), u AS (
    INSERT INTO public.org_units (id, organization_id, path, type, code, name)
    VALUES (gen_random_uuid(), $2, $3::ltree, 'department', $3, $3) RETURNING id
)
INSERT INTO public.member_org_units (id, organization_id, member_id, org_unit_id, relation)
SELECT $1, $2, m.id, u.id, 'primary' FROM m, u
"""


async def test_member_org_units_tenant_isolation(make_pool: PoolFactory, isolation_db: IsolationDb) -> None:
    await assert_tenant_isolation(
        make_pool, isolation_db, "member_org_units", INSERT, update_column="relation"
    )
