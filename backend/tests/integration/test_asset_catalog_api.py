# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Catalog reference data API: categories, custom field definitions, manufacturers, suppliers
(M2.1-T1/T2 data, §B8.1, P8-06): permission, version conflict, archive-blocked, type-change-blocked,
audit+outbox, isolation and seed idempotency, all against a real disposable PostgreSQL."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import httpx
import pytest
from pg_harness import PoolFactory

from app.core.db import Pool, tenant_transaction
from app.main import create_app
from app.modules.organization.modules import install_module


async def _create_org(pool: Pool, *, domain_key: str = "generic") -> UUID:
    org_id = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.organizations"
            " (id, slug, name, idp_organization_id, domain_key, settings)"
            " VALUES ($1, $2, 'Catalog API Org', $3, $4, '{}'::jsonb)",
            org_id,
            f"catalog-api-{org_id.hex[:12]}",
            f"idp-catalog-api-{uuid4().hex[:12]}",
            domain_key,
        )
        await install_module(conn, org_id, "assets")
    return org_id


@pytest.fixture
async def client(make_pool: PoolFactory) -> AsyncIterator[httpx.AsyncClient]:
    pool = await make_pool("api")
    app = create_app()
    app.state.pool = pool
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _headers(org_id: UUID, role: str = "admin") -> dict[str, str]:
    return {"x-member-id": str(uuid4()), "x-organization-id": str(org_id), "x-role": role}


# ==============================================================================
# Asset categories
# ==============================================================================


async def test_create_category_requires_write_permission(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    res = await client.post(
        "/api/v1/asset-categories",
        json={"code": "computer", "name": "Computers"},
        headers=_headers(org_id, role="member"),
    )
    assert res.status_code == 403
    assert res.json()["code"] == "auth.permission_denied"


async def test_read_category_allowed_at_self_scope(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    """A `member` role (asset.read only, no scope restriction on this organization-wide data) can
    still read categories, because it must see the category of the assets it holds (§B8.1)."""
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    create_res = await client.post(
        "/api/v1/asset-categories", json={"code": "computer", "name": "Computers"}, headers=_headers(org_id)
    )
    assert create_res.status_code == 201

    res = await client.get("/api/v1/asset-categories", headers=_headers(org_id, role="member"))
    assert res.status_code == 200
    codes = [c["code"] for c in res.json()["data"]["items"]]
    assert "computer" in codes


async def test_create_update_archive_category_lifecycle(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    headers = _headers(org_id)

    create_res = await client.post(
        "/api/v1/asset-categories",
        json={"code": "computer", "name": "Computers", "default_criticality": "medium"},
        headers=headers,
    )
    assert create_res.status_code == 201
    category = create_res.json()["data"]
    category_id = category["id"]
    assert category["version"] == 1
    assert category["status"] == "active"

    update_res = await client.patch(
        f"/api/v1/asset-categories/{category_id}",
        json={"name": "Desktop computers", "version": 1},
        headers=headers,
    )
    assert update_res.status_code == 200
    assert update_res.json()["data"]["name"] == "Desktop computers"
    assert update_res.json()["data"]["version"] == 2

    # Stale version is refused.
    stale_res = await client.patch(
        f"/api/v1/asset-categories/{category_id}", json={"name": "x", "version": 1}, headers=headers
    )
    assert stale_res.status_code == 409
    assert stale_res.json()["code"] == "asset_category.version_conflict"

    archive_res = await client.post(
        f"/api/v1/asset-categories/{category_id}/archive", json={"version": 2}, headers=headers
    )
    assert archive_res.status_code == 200
    assert archive_res.json()["data"]["status"] == "archived"

    async with tenant_transaction(pool, org_id) as conn:
        action = await conn.fetchval(
            "SELECT action FROM public.audit_events"
            " WHERE organization_id = $1 AND entity_type = 'asset_category'"
            " AND action = 'asset_category.archive'",
            org_id,
        )
        outbox_event = await conn.fetchval(
            "SELECT event_type FROM public.outbox"
            " WHERE organization_id = $1 AND event_type = 'asset_category.archived'",
            org_id,
        )
    assert action == "asset_category.archive"
    assert outbox_event == "asset_category.archived"


async def test_move_category_refuses_cycle(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    headers = _headers(org_id)

    parent_res = await client.post(
        "/api/v1/asset-categories", json={"code": "computer", "name": "Computers"}, headers=headers
    )
    parent_id = parent_res.json()["data"]["id"]
    child_res = await client.post(
        "/api/v1/asset-categories",
        json={"code": "laptop", "name": "Laptops", "parent_id": parent_id},
        headers=headers,
    )
    child_id = child_res.json()["data"]["id"]

    move_res = await client.post(
        f"/api/v1/asset-categories/{parent_id}/move",
        json={"new_parent_id": child_id, "version": 1},
        headers=headers,
    )
    assert move_res.status_code == 409
    assert move_res.json()["code"] == "asset_category.invalid_move"


async def test_archive_category_blocked_by_active_child_then_allowed(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    headers = _headers(org_id)

    parent_res = await client.post(
        "/api/v1/asset-categories", json={"code": "computer", "name": "Computers"}, headers=headers
    )
    parent_id = parent_res.json()["data"]["id"]
    child_res = await client.post(
        "/api/v1/asset-categories",
        json={"code": "laptop", "name": "Laptops", "parent_id": parent_id},
        headers=headers,
    )
    child_id = child_res.json()["data"]["id"]

    blocked_res = await client.post(
        f"/api/v1/asset-categories/{parent_id}/archive", json={"version": 1}, headers=headers
    )
    assert blocked_res.status_code == 409
    assert blocked_res.json()["code"] == "asset_category.archive_blocked"

    archive_child_res = await client.post(
        f"/api/v1/asset-categories/{child_id}/archive", json={"version": 1}, headers=headers
    )
    assert archive_child_res.status_code == 200

    allowed_res = await client.post(
        f"/api/v1/asset-categories/{parent_id}/archive", json={"version": 1}, headers=headers
    )
    assert allowed_res.status_code == 200


# ==============================================================================
# Custom field definitions
# ==============================================================================


async def test_custom_field_definition_create_validation_and_lifecycle(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    headers = _headers(org_id)
    category_res = await client.post(
        "/api/v1/asset-categories", json={"code": "computer", "name": "Computers"}, headers=headers
    )
    category_id = category_res.json()["data"]["id"]

    # Definition-time rule: min > max is refused (P8-04 rules, reused here).
    invalid_res = await client.post(
        f"/api/v1/asset-categories/{category_id}/custom-fields",
        json={"key": "ram_gb", "label": "RAM (GB)", "field_type": "number", "min": 10, "max": 1},
        headers=headers,
    )
    assert invalid_res.status_code == 422

    create_res = await client.post(
        f"/api/v1/asset-categories/{category_id}/custom-fields",
        json={
            "key": "ram_gb",
            "label": "RAM (GB)",
            "field_type": "number",
            "min": 1,
            "max": 256,
            "is_required": True,
        },
        headers=headers,
    )
    assert create_res.status_code == 201
    field = create_res.json()["data"]
    assert field["rules"] == {"min": 1, "max": 256}

    # Duplicate key on the same category is refused.
    dup_res = await client.post(
        f"/api/v1/asset-categories/{category_id}/custom-fields",
        json={"key": "ram_gb", "label": "RAM again", "field_type": "number"},
        headers=headers,
    )
    assert dup_res.status_code == 409

    update_res = await client.patch(
        f"/api/v1/asset-categories/{category_id}/custom-fields/{field['id']}",
        json={"label": "RAM in GB", "version": 1},
        headers=headers,
    )
    assert update_res.status_code == 200
    assert update_res.json()["data"]["label"] == "RAM in GB"

    archive_res = await client.post(
        f"/api/v1/asset-categories/{category_id}/custom-fields/{field['id']}/archive",
        json={"version": 2},
        headers=headers,
    )
    assert archive_res.status_code == 200
    assert archive_res.json()["data"]["status"] == "archived"


async def test_custom_field_type_change_refused_once_asset_has_value(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    headers = _headers(org_id)
    category_res = await client.post(
        "/api/v1/asset-categories", json={"code": "computer", "name": "Computers"}, headers=headers
    )
    category_id = category_res.json()["data"]["id"]
    field_res = await client.post(
        f"/api/v1/asset-categories/{category_id}/custom-fields",
        json={"key": "serial", "label": "Serial", "field_type": "text"},
        headers=headers,
    )
    field_id = field_res.json()["data"]["id"]

    # Simulate an asset already storing a value for this field key.
    async with tenant_transaction(pool, org_id) as conn:
        org_unit_id = await conn.fetchval(
            "SELECT id FROM public.org_units WHERE organization_id = $1 LIMIT 1", org_id
        )
        if org_unit_id is None:
            org_unit_id = uuid4()
            await conn.execute(
                "INSERT INTO public.org_units"
                " (id, organization_id, parent_id, path, type, code, name, status, version) "
                "VALUES ($1, $2, NULL, 'root'::ltree, 'root', 'root', 'Root', 'active', 1)",
                org_unit_id,
                org_id,
            )
        await conn.execute(
            "INSERT INTO public.assets "
            "(id, organization_id, tag, name, category_id, owner_org_unit_id, owner_org_unit_path, "
            "status, custom_fields, version) "
            "VALUES ($1, $2, 'AST-0001', 'Laptop 1', $3, $4, 'root'::ltree, 'active', $5::jsonb, 1)",
            uuid4(),
            org_id,
            UUID(category_id),
            org_unit_id,
            json.dumps({"serial": "abc123"}),
        )

    blocked_res = await client.patch(
        f"/api/v1/asset-categories/{category_id}/custom-fields/{field_id}",
        json={"field_type": "number", "version": 1},
        headers=headers,
    )
    assert blocked_res.status_code == 409
    assert blocked_res.json()["code"] == "custom_field_definition.type_change_blocked"

    # Changing something other than the type still works.
    label_res = await client.patch(
        f"/api/v1/asset-categories/{category_id}/custom-fields/{field_id}",
        json={"label": "Serial number", "version": 1},
        headers=headers,
    )
    assert label_res.status_code == 200


# ==============================================================================
# Manufacturers and suppliers
# ==============================================================================


async def test_manufacturer_lifecycle(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    headers = _headers(org_id)

    create_res = await client.post(
        "/api/v1/manufacturers",
        json={"name": "Acme Corp", "contact": {"email": "sales@acme.test"}},
        headers=headers,
    )
    assert create_res.status_code == 201
    manufacturer_id = create_res.json()["data"]["id"]

    dup_res = await client.post("/api/v1/manufacturers", json={"name": "Acme Corp"}, headers=headers)
    assert dup_res.status_code == 409

    update_res = await client.patch(
        f"/api/v1/manufacturers/{manufacturer_id}",
        json={"notes": "preferred vendor", "version": 1},
        headers=headers,
    )
    assert update_res.status_code == 200

    archive_res = await client.post(
        f"/api/v1/manufacturers/{manufacturer_id}/archive", json={"version": 2}, headers=headers
    )
    assert archive_res.status_code == 200
    assert archive_res.json()["data"]["status"] == "archived"
