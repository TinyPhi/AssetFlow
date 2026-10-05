# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Scope handling for the catalog reference data API (§B8.1, P8-06).

This reference data is organization-wide (§B7.1): a member scoped only to `self` (the baseline
scope every member has for their own held assets) can still read categories and custom field
definitions, but only an organization-scope grant of `asset.update` may write them - a narrower
org-unit/team/self grant of the same permission is refused, even though it "has" the permission.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import httpx
import pytest
from pg_harness import PoolFactory

from app.core.db import Pool, tenant_transaction
from app.main import create_app
from app.modules.organization.modules import install_module


async def _create_org(pool: Pool) -> str:
    org_id = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.organizations"
            " (id, slug, name, idp_organization_id, domain_key, settings)"
            " VALUES ($1, $2, 'Catalog Scope Org', $3, 'generic', '{}'::jsonb)",
            org_id,
            f"catalog-scope-{org_id.hex[:12]}",
            f"idp-catalog-scope-{uuid4().hex[:12]}",
        )
        await install_module(conn, org_id, "assets")
    return str(org_id)


@pytest.fixture
async def client(make_pool: PoolFactory) -> AsyncIterator[httpx.AsyncClient]:
    pool = await make_pool("api")
    app = create_app()
    app.state.pool = pool
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _self_scope_headers(org_id: str, member_id: str | None = None) -> dict[str, str]:
    """A `member` role: `asset.read`/`asset.acknowledge` only, baseline `self` scope, no `asset.update`."""
    return {
        "x-member-id": member_id or str(uuid4()),
        "x-organization-id": org_id,
        "x-role": "member",
        "x-scope-type": "self",
    }


def _org_unit_scoped_asset_manager_headers(org_id: str) -> dict[str, str]:
    """An `asset_manager` grant scoped to one org unit (not organization-wide): has `asset.update`
    as a *permission*, but not at organization scope, so this reference data write must still be
    refused (§B7.1: organization-wide data needs an organization-scope grant)."""
    return {
        "x-member-id": str(uuid4()),
        "x-organization-id": org_id,
        "x-role": "asset_manager",
        "x-scope-type": "org_unit",
        "x-org-unit-path": "root.hq",
    }


def _org_scoped_asset_manager_headers(org_id: str) -> dict[str, str]:
    return {
        "x-member-id": str(uuid4()),
        "x-organization-id": org_id,
        "x-role": "asset_manager",
        "x-scope-type": "organization",
    }


async def test_self_scope_member_can_read_categories(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    create_res = await client.post(
        "/api/v1/asset-categories",
        json={"code": "computer", "name": "Computers"},
        headers=_org_scoped_asset_manager_headers(org_id),
    )
    assert create_res.status_code == 201

    res = await client.get("/api/v1/asset-categories", headers=_self_scope_headers(org_id))
    assert res.status_code == 200
    codes = [c["code"] for c in res.json()["data"]["items"]]
    assert "computer" in codes


async def test_self_scope_member_cannot_write_categories(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    res = await client.post(
        "/api/v1/asset-categories",
        json={"code": "computer", "name": "Computers"},
        headers=_self_scope_headers(org_id),
    )
    assert res.status_code == 403
    assert res.json()["code"] == "auth.permission_denied"


async def test_org_unit_scoped_grant_cannot_write_organization_wide_reference_data(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    """`asset.update` held only at org-unit scope is refused for this organization-wide table,
    even though the same role, held at organization scope, is accepted (next test)."""
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    res = await client.post(
        "/api/v1/asset-categories",
        json={"code": "computer", "name": "Computers"},
        headers=_org_unit_scoped_asset_manager_headers(org_id),
    )
    assert res.status_code == 403
    assert res.json()["code"] == "scope.denied"  # held, but not at organization scope (§C4.5)


async def test_organization_scoped_grant_can_write(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    res = await client.post(
        "/api/v1/asset-categories",
        json={"code": "computer", "name": "Computers"},
        headers=_org_scoped_asset_manager_headers(org_id),
    )
    assert res.status_code == 201
