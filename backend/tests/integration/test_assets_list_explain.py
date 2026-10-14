# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""EXPLAIN proof for the asset list query on 10,000 assets (§C11 Data, §B5.3, P8-07).

Under enforced row level security (the `api` role) the team and self scope branches use their
equality indexes. The org-unit-path (`<@`) and trigram (`%`) predicates are post-filters there: a
PostgreSQL planner only pushes a qual below the row-security barrier when its operator is
LEAKPROOF, and neither ltree `<@` nor pg_trgm `%` is (the known limitation recorded in P8-03).
The same predicates do use their GiST / GIN indexes when row security does not apply (superuser),
which proves the indexes themselves are well-formed.
"""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

import asyncpg
import pytest
from pg_harness import IsolationDb, PoolFactory

from app.core.db import tenant_transaction
from app.core.permissions import ScopeFilter
from app.modules.assets import repository as repo

ASSET_COUNT = 10_000


class _ExplainConn:
    """Runs the repository's own SQL under EXPLAIN and keeps the plan text."""

    def __init__(self, conn: Any) -> None:
        self.conn = conn
        self.plan = ""

    async def fetch(self, sql: str, *args: object) -> list[object]:
        rows = await self.conn.fetch("EXPLAIN (COSTS OFF) " + sql, *args)
        self.plan = "\n".join(r[0] for r in rows)
        return []

    async def fetchval(self, sql: str, *args: object) -> int:
        return 0


@pytest.fixture
async def seeded(isolation_db: IsolationDb) -> tuple[UUID, UUID, UUID]:
    org = isolation_db.org_a
    su = await asyncpg.connect(isolation_db.admin_dsn)
    try:
        await su.execute(
            "INSERT INTO public.org_units (id, organization_id, parent_id, path, type, code, name) "
            "SELECT gen_random_uuid(), $1, NULL, ('u' || g)::ltree, 'unit', 'u' || g, 'u' || g "
            "FROM generate_series(1, 40) g",
            org,
        )
        await su.execute(
            "INSERT INTO public.asset_categories (id, organization_id, parent_id, path, code, name) "
            "VALUES (gen_random_uuid(), $1, NULL, 'cat', 'cat', 'cat')",
            org,
        )
        await su.execute(
            "INSERT INTO public.teams (id, organization_id, type, code, name) "
            "SELECT gen_random_uuid(), $1, 'team', 't' || g, 't' || g FROM generate_series(1, 20) g",
            org,
        )
        await su.execute(
            "INSERT INTO public.members (id, organization_id, idp_subject, email, display_name, status) "
            "SELECT gen_random_uuid(), $1, 's' || g, 'm' || g || '@x.test', 'm' || g, 'active' "
            "FROM generate_series(1, 50) g",
            org,
        )
        await su.execute(
            "INSERT INTO public.assets (id, organization_id, tag, name, category_id, serial_number, "
            "owner_org_unit_id, status, criticality, version, holder_team_id, holder_member_id) "
            "SELECT gen_random_uuid(), $1, 'AST-' || lpad(g::text, 6, '0'), md5(g::text), "
            "(SELECT id FROM public.asset_categories WHERE organization_id = $1 LIMIT 1), "
            "'SN' || md5((g * 7)::text), "
            "(SELECT id FROM public.org_units WHERE organization_id = $1 AND code = 'u' || (1 + g % 40)), "
            "'active', 'low', 1, "
            "CASE WHEN g % 20 = 1 THEN (SELECT id FROM public.teams WHERE organization_id = $1 "
            "AND code = 't' || (1 + g % 20)) END, "
            "CASE WHEN g % 20 = 2 THEN (SELECT id FROM public.members WHERE organization_id = $1 "
            "AND idp_subject = 's' || (1 + g % 50)) END "
            "FROM generate_series(1, $2) g",
            org,
            ASSET_COUNT,
        )
        await su.execute("ANALYZE public.assets")
        team = await su.fetchval("SELECT id FROM public.teams WHERE organization_id = $1 LIMIT 1", org)
        member = await su.fetchval("SELECT id FROM public.members WHERE organization_id = $1 LIMIT 1", org)
    finally:
        await su.close()
    return org, team, member


async def test_scope_branches_use_their_indexes_on_10k_assets(
    make_pool: PoolFactory, isolation_db: IsolationDb, seeded: tuple[UUID, UUID, UUID]
) -> None:
    org, team, member = seeded
    pool = await make_pool("api")
    scope = ScopeFilter(org_unit_paths=("u7",), team_ids=(str(team),), member_id=str(member))

    async with tenant_transaction(pool, org) as conn:
        explain = _ExplainConn(conn)
        await repo.AssetRepository().list_assets(
            explain,  # type: ignore[arg-type]
            organization_id=org,
            scope_filter=scope,
            query=repo.AssetQuery(),
            limit=51,
        )
    # Equality branches: indexed even under enforced row level security.
    assert "ix_assets__organization_id_holder_team_id" in explain.plan
    assert "ix_assets__organization_id_holder_member_id" in explain.plan
    # Path branch: a post-filter under row level security (ltree `<@` is not leakproof).
    assert "owner_org_unit_path <@ ANY" in explain.plan

    su = await asyncpg.connect(isolation_db.admin_dsn)
    try:
        superuser = _ExplainConn(su)
        await repo.AssetRepository().list_assets(
            superuser,  # type: ignore[arg-type]
            organization_id=org,
            scope_filter=scope,
            query=repo.AssetQuery(),
            limit=51,
        )
        # Without row level security the same predicate uses its GiST index.
        assert "ix_assets__organization_id_owner_org_unit_path_gist" in superuser.plan

        # The trigram indexes are well-formed and used by the same `%` operator the list query
        # emits. (The list query ORs four columns; at 10,000 rows the planner prefers the
        # organization index plus a filter for that shape, a costing choice, not an index defect.)
        term = hashlib.md5(b"5000", usedforsecurity=False).hexdigest()[:8]
        await su.execute("SET enable_seqscan = off")
        for column in ("name", "serial_number"):
            rows = await su.fetch(f"EXPLAIN SELECT 1 FROM public.assets WHERE {column} % $1", term)  # noqa: S608
            plan = " ".join(r[0] for r in rows)
            assert f"ix_assets__{column}_trgm" in plan, plan
    finally:
        await su.close()
