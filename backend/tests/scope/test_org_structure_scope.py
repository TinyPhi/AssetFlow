# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Scope leakage and boundary enforcement tests for organization structure (§M1.4-T4, §M1.4-T5).

Verifies:
- Scoped callers only see and manage entities within their grant's subtree/team.
- Accessing entities outside caller scope answers 404, never 403.
- List endpoints filter results strictly to allowed scope.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pg_harness import PoolFactory

from app.core.db import Pool, tenant_transaction
from app.main import create_app
from app.providers.auth.mock import MockAuthProvider
from app.providers.context import ProviderContext


@dataclass
class _Registry:
    auth: MockAuthProvider


async def _make_client(pool: Pool) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()
    app.state.registry = _Registry(auth=MockAuthProvider(ProviderContext("test", "auth", Path())))
    app.state.pool = pool
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def client(make_pool: PoolFactory) -> AsyncIterator[httpx.AsyncClient]:
    pool = await make_pool("api")
    async for c in _make_client(pool):
        yield c


async def test_org_unit_scope_leakage_and_404_denial(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id = uuid4()
    root_unit_id = uuid4()
    hq_unit_id = uuid4()
    ops_unit_id = uuid4()
    scoped_member_id = uuid4()

    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.organizations (id, slug, name, domain_key, idp_organization_id, status) "
            "VALUES ($1, $2, 'Scope Test Org', 'generic', $3, 'active')",
            org_id,
            f"org-{uuid4().hex[:8]}",
            f"idp-{uuid4().hex[:8]}",
        )
        # Root unit
        await conn.execute(
            "INSERT INTO public.org_units "
            "(id, organization_id, parent_id, path, type, code, name, status, version) "
            "VALUES ($1, $2, NULL, 'root'::ltree, 'root', 'root', 'Root', 'active', 1)",
            root_unit_id,
            org_id,
        )
        # HQ unit (root.hq)
        await conn.execute(
            "INSERT INTO public.org_units "
            "(id, organization_id, parent_id, path, type, code, name, status, version) "
            "VALUES ($1, $2, $3, 'root.hq'::ltree, 'division', 'hq', 'Headquarters', 'active', 1)",
            hq_unit_id,
            org_id,
            root_unit_id,
        )
        # OPS unit (root.ops)
        await conn.execute(
            "INSERT INTO public.org_units "
            "(id, organization_id, parent_id, path, type, code, name, status, version) "
            "VALUES ($1, $2, $3, 'root.ops'::ltree, 'division', 'ops', 'Operations', 'active', 1)",
            ops_unit_id,
            org_id,
            root_unit_id,
        )
        # Member scoped only to root.hq
        await conn.execute(
            "INSERT INTO public.members (id, organization_id, email, status, idp_subject, display_name) "
            "VALUES ($1, $2, 'hq_admin@example.test', 'active', $3, 'HQ Admin')",
            scoped_member_id,
            org_id,
            f"sub-{scoped_member_id}",
        )
        await conn.execute(
            "INSERT INTO public.role_grants (id, organization_id, member_id, role_key, scope_type, scope_id) "
            "VALUES ($1, $2, $3, 'admin', 'org_unit', $4)",
            uuid4(),
            org_id,
            scoped_member_id,
            hq_unit_id,
        )

    hq_headers = {
        "x-organization-id": str(org_id),
        "x-member-id": str(scoped_member_id),
        "x-role": "admin",
        "x-scope-type": "org_unit",
        "x-org-unit-path": "root.hq",
    }

    # 1. Scoped caller listing org units only sees root.hq and below
    res = await client.get("/api/v1/org-units", headers=hq_headers)
    assert res.status_code == 200
    units = res.json()["data"]
    unit_codes = [u["code"] for u in units]
    assert "hq" in unit_codes
    assert "ops" not in unit_codes
    assert "root" not in unit_codes

    # 2. Scoped caller reading allowed unit -> 200 OK
    res = await client.get(f"/api/v1/org-units/{hq_unit_id}", headers=hq_headers)
    assert res.status_code == 200

    # 3. Scoped caller reading unit OUTSIDE scope -> 404 Not Found (never 403)
    res = await client.get(f"/api/v1/org-units/{ops_unit_id}", headers=hq_headers)
    assert res.status_code == 404
    assert res.json()["code"] == "org_unit.not_found"


async def test_team_scope_filtering_and_404_denial(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = uuid4()
    team_a_id = uuid4()
    team_b_id = uuid4()
    scoped_member_id = uuid4()

    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.organizations (id, slug, name, domain_key, idp_organization_id, status) "
            "VALUES ($1, $2, 'Team Scope Org', 'generic', $3, 'active')",
            org_id,
            f"org-{uuid4().hex[:8]}",
            f"idp-{uuid4().hex[:8]}",
        )
        await conn.execute(
            "INSERT INTO public.teams (id, organization_id, code, name, type, status, version) "
            "VALUES ($1, $2, 'team-a', 'Team Alpha', 'maintenance', 'active', 1)",
            team_a_id,
            org_id,
        )
        await conn.execute(
            "INSERT INTO public.teams (id, organization_id, code, name, type, status, version) "
            "VALUES ($1, $2, 'team-b', 'Team Beta', 'maintenance', 'active', 1)",
            team_b_id,
            org_id,
        )
        await conn.execute(
            "INSERT INTO public.members (id, organization_id, email, status, idp_subject, display_name) "
            "VALUES ($1, $2, 'team_user@example.test', 'active', $3, 'Team User')",
            scoped_member_id,
            org_id,
            f"sub-{scoped_member_id}",
        )
        # Grant scoped to Team Alpha
        await conn.execute(
            "INSERT INTO public.role_grants (id, organization_id, member_id, role_key, scope_type, scope_id) "
            "VALUES ($1, $2, $3, 'admin', 'team', $4)",
            uuid4(),
            org_id,
            scoped_member_id,
            team_a_id,
        )

    team_headers = {
        "x-organization-id": str(org_id),
        "x-member-id": str(scoped_member_id),
        "x-role": "admin",
        "x-scope-type": "team",
        "x-team-ids": str(team_a_id),
    }

    # 1. Listing teams only shows Team Alpha
    res = await client.get("/api/v1/teams", headers=team_headers)
    assert res.status_code == 200
    teams = res.json()["data"]
    team_codes = [t["code"] for t in teams]
    assert "team-a" in team_codes
    assert "team-b" not in team_codes

    # 2. Reading Team Alpha -> 200 OK
    res = await client.get(f"/api/v1/teams/{team_a_id}", headers=team_headers)
    assert res.status_code == 200

    # 3. Reading Team Beta OUTSIDE scope -> 404 Not Found (never 403)
    res = await client.get(f"/api/v1/teams/{team_b_id}", headers=team_headers)
    assert res.status_code == 404
    assert res.json()["code"] == "team.not_found"
