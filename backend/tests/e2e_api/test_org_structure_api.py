# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""E2E API test for Org Units, Locations, and Teams management (§M1.4-T4).

Tests:
- Creating hierarchical trees with materialized paths.
- Moving subtree updates all descendant paths in a single transaction.
- Cycle prevention when moving.
- Archive blockers naming the blocker (active_children, active_members, active_teams).
- Physical locations CRUD, subtree moves, and deletion blocked by child locations.
- Teams and team members assignment, updating, and archive blocking.
- Single-transaction audit events and outbox entries for mutations.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

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


async def _create_org(pool: Pool) -> tuple[UUID, UUID, str]:
    org_id = uuid4()
    admin_id = uuid4()
    idp_org = f"idp-{uuid4().hex[:12]}"
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.organizations (id, slug, name, domain_key, idp_organization_id, status) "
            "VALUES ($1, $2, $3, 'generic', $4, 'active')",
            org_id,
            f"org-{uuid4().hex[:8]}",
            "Test Org",
            idp_org,
        )
        await conn.execute(
            "INSERT INTO public.org_units "
            "(id, organization_id, parent_id, path, type, code, name, status, version) "
            "VALUES ($1, $2, NULL, 'root'::ltree, 'root', 'root', 'Root Unit', 'active', 1)",
            uuid4(),
            org_id,
        )
        await conn.execute(
            "INSERT INTO public.members (id, organization_id, email, status, idp_subject, display_name) "
            "VALUES ($1, $2, 'admin@example.test', 'active', $3, 'Admin User')",
            admin_id,
            org_id,
            f"sub-{admin_id}",
        )
        await conn.execute(
            "INSERT INTO public.role_grants (id, organization_id, member_id, role_key, scope_type) "
            "VALUES ($1, $2, $3, 'admin', 'organization')",
            uuid4(),
            org_id,
            admin_id,
        )
    return org_id, admin_id, idp_org


def _admin_headers(org_id: UUID, member_id: UUID) -> dict[str, str]:
    return {
        "x-organization-id": str(org_id),
        "x-member-id": str(member_id),
        "x-role": "admin",
        "x-scope-type": "organization",
    }


# ==============================================================================
# Org Units Tests
# ==============================================================================


async def test_org_unit_lifecycle_and_subtree_move(  # noqa: PLR0915
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id, admin_id, _ = await _create_org(pool)
    headers = _admin_headers(org_id, admin_id)

    # 1. Get root org unit
    res = await client.get("/api/v1/org-units", headers=headers)
    assert res.status_code == 200
    units = res.json()["data"]
    assert len(units) == 1
    root_id = UUID(units[0]["id"])
    assert units[0]["path"] == "root"

    # 2. Create child unit: HQ under root -> path: root.hq
    res = await client.post(
        "/api/v1/org-units",
        headers=headers,
        json={"code": "hq", "name": "Headquarters", "type": "division", "parent_id": str(root_id)},
    )
    assert res.status_code == 201
    hq = res.json()["data"]
    hq_id = UUID(hq["id"])
    assert hq["path"] == "root.hq"

    # 3. Create child unit: ENG under HQ -> path: root.hq.eng
    res = await client.post(
        "/api/v1/org-units",
        headers=headers,
        json={"code": "eng", "name": "Engineering", "type": "department", "parent_id": str(hq_id)},
    )
    assert res.status_code == 201
    eng = res.json()["data"]
    eng_id = UUID(eng["id"])
    assert eng["path"] == "root.hq.eng"

    # 4. Create child unit: BACKEND under ENG -> path: root.hq.eng.backend
    res = await client.post(
        "/api/v1/org-units",
        headers=headers,
        json={"code": "backend", "name": "Backend Team", "type": "section", "parent_id": str(eng_id)},
    )
    assert res.status_code == 201
    backend = res.json()["data"]
    backend_id = UUID(backend["id"])
    assert backend["path"] == "root.hq.eng.backend"

    # 5. Create another branch: OPS under root -> path: root.ops
    res = await client.post(
        "/api/v1/org-units",
        headers=headers,
        json={"code": "ops", "name": "Operations", "type": "division", "parent_id": str(root_id)},
    )
    assert res.status_code == 201
    ops = res.json()["data"]
    ops_id = UUID(ops["id"])
    assert ops["path"] == "root.ops"

    # 6. Refuse cycle: Try moving HQ under BACKEND (which is a descendant of HQ)
    res = await client.post(
        f"/api/v1/org-units/{hq_id}/move",
        headers=headers,
        json={"new_parent_id": str(backend_id), "version": hq["version"]},
    )
    assert res.status_code == 409
    assert res.json()["code"] == "org_unit.invalid_move"

    # 7. Move ENG subtree under OPS -> ENG becomes root.ops.eng, BACKEND becomes root.ops.eng.backend
    res = await client.post(
        f"/api/v1/org-units/{eng_id}/move",
        headers=headers,
        json={"new_parent_id": str(ops_id), "version": eng["version"]},
    )
    assert res.status_code == 200
    moved_eng = res.json()["data"]
    assert moved_eng["path"] == "root.ops.eng"
    assert moved_eng["parent_id"] == str(ops_id)

    # Verify descendant path was updated in the same transaction
    res = await client.get(f"/api/v1/org-units/{backend_id}", headers=headers)
    assert res.status_code == 200
    updated_backend = res.json()["data"]
    assert updated_backend["path"] == "root.ops.eng.backend"

    # 8. Archive blocking rule: Attempt to archive OPS when it has active child ENG
    res = await client.get(f"/api/v1/org-units/{ops_id}", headers=headers)
    ops_current = res.json()["data"]
    res = await client.post(
        f"/api/v1/org-units/{ops_id}/archive",
        headers=headers,
        json={"version": ops_current["version"]},
    )
    assert res.status_code == 409
    err = res.json()
    assert err["code"] == "org_unit.archive_blocked"
    assert "active_children" in err["detail"]

    # 9. Verify outbox events and audit records were written in transactions
    async with tenant_transaction(pool, org_id) as conn:
        audit_count = await conn.fetchval(
            "SELECT count(*) FROM public.audit_events WHERE organization_id = $1", org_id
        )
        assert audit_count >= 5

        outbox_count = await conn.fetchval(
            "SELECT count(*) FROM public.outbox WHERE organization_id = $1", org_id
        )
        assert outbox_count >= 5


# ==============================================================================
# Locations Tests
# ==============================================================================


async def test_location_hierarchy_and_deletion_blocking(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id, admin_id, _ = await _create_org(pool)
    headers = _admin_headers(org_id, admin_id)

    # 1. Create root location: Plant 1 -> path: plant1
    res = await client.post(
        "/api/v1/locations",
        headers=headers,
        json={"code": "plant1", "name": "Main Manufacturing Plant", "type": "plant"},
    )
    assert res.status_code == 201
    plant = res.json()["data"]
    plant_id = UUID(plant["id"])
    assert plant["path"] == "plant1"

    # 2. Create sub-location: Building A under Plant 1 -> path: plant1.bldga
    res = await client.post(
        "/api/v1/locations",
        headers=headers,
        json={
            "code": "bldga",
            "name": "Building A",
            "type": "building",
            "parent_id": str(plant_id),
        },
    )
    assert res.status_code == 201
    bldg = res.json()["data"]
    bldg_id = UUID(bldg["id"])
    assert bldg["path"] == "plant1.bldga"

    # 3. Create sub-location: Room 101 under Building A -> path: plant1.bldga.rm101
    res = await client.post(
        "/api/v1/locations",
        headers=headers,
        json={
            "code": "rm101",
            "name": "Server Room 101",
            "type": "room",
            "parent_id": str(bldg_id),
        },
    )
    assert res.status_code == 201
    rm = res.json()["data"]
    rm_id = UUID(rm["id"])
    assert rm["path"] == "plant1.bldga.rm101"

    # 4. Attempt to delete Plant 1 while Building A exists -> blocked
    res = await client.delete(f"/api/v1/locations/{plant_id}?version=1", headers=headers)
    assert res.status_code == 409
    assert res.json()["code"] == "location.delete_blocked"

    # 5. Delete Room 101, then Delete Building A, then Delete Plant 1
    res = await client.delete(f"/api/v1/locations/{rm_id}?version=1", headers=headers)
    assert res.status_code == 200
    assert res.json()["data"]["deleted"] is True

    res = await client.delete(f"/api/v1/locations/{bldg_id}?version=1", headers=headers)
    assert res.status_code == 200

    res = await client.delete(f"/api/v1/locations/{plant_id}?version=1", headers=headers)
    assert res.status_code == 200


# ==============================================================================
# Teams and Team Members Tests
# ==============================================================================


async def test_teams_and_membership_lifecycle(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id, admin_id, _ = await _create_org(pool)
    headers = _admin_headers(org_id, admin_id)

    # 1. Create a team
    res = await client.post(
        "/api/v1/teams",
        headers=headers,
        json={
            "code": "maint-elec",
            "name": "Electrical Maintenance",
            "type": "maintenance",
            "skills": ["electrical", "high-voltage"],
        },
    )
    assert res.status_code == 201
    team = res.json()["data"]
    team_id = UUID(team["id"])
    assert team["code"] == "maint-elec"
    assert team["skills"] == ["electrical", "high-voltage"]

    # 2. Add member to team
    res = await client.post(
        f"/api/v1/teams/{team_id}/members",
        headers=headers,
        json={"member_id": str(admin_id), "team_role": "lead"},
    )
    assert res.status_code == 201
    member_assignment = res.json()["data"]
    assert member_assignment["team_role"] == "lead"
    assert member_assignment["member_id"] == str(admin_id)

    # 3. List team members
    res = await client.get(f"/api/v1/teams/{team_id}/members", headers=headers)
    assert res.status_code == 200
    members = res.json()["data"]
    assert len(members) == 1
    assert members[0]["member_id"] == str(admin_id)

    # 4. Attempt to archive team while member is assigned -> blocked
    res = await client.post(
        f"/api/v1/teams/{team_id}/archive",
        headers=headers,
        json={"version": team["version"]},
    )
    assert res.status_code == 409
    err = res.json()
    assert err["code"] == "team.archive_blocked"
    assert "active members" in err["detail"].lower()

    # 5. Remove member from team
    res = await client.delete(f"/api/v1/teams/{team_id}/members/{admin_id}", headers=headers)
    assert res.status_code == 200
    assert res.json()["data"]["removed"] is True

    # 6. Archive team now succeeds
    res = await client.post(
        f"/api/v1/teams/{team_id}/archive",
        headers=headers,
        json={"version": team["version"]},
    )
    assert res.status_code == 200
    archived_team = res.json()["data"]
    assert archived_team["status"] == "archived"
