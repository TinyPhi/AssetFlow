# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Tenant isolation tests for team_members (§B5.2, §B10, §C4.8, §C8.5)."""

from __future__ import annotations

from pg_harness import IsolationDb, PoolFactory
from tenant_checks import assert_tenant_isolation

# The member and the team are created in the same statement and organization.
INSERT = """
WITH m AS (
    INSERT INTO public.members (id, organization_id, idp_subject, email, display_name)
    VALUES (gen_random_uuid(), $2, $3, $3 || '@example.test', $3) RETURNING id
), t AS (
    INSERT INTO public.teams (id, organization_id, code, name, type)
    VALUES (gen_random_uuid(), $2, $3, $3, 'core') RETURNING id
)
INSERT INTO public.team_members (id, organization_id, team_id, member_id, team_role)
SELECT $1, $2, t.id, m.id, 'member' FROM m, t
"""


async def test_team_members_tenant_isolation(make_pool: PoolFactory, isolation_db: IsolationDb) -> None:
    await assert_tenant_isolation(make_pool, isolation_db, "team_members", INSERT, update_column="team_role")
