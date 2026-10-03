# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Organization settings API: permission, validation, audit per change (M1.4-T9)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import httpx
import pytest
from pg_harness import PoolFactory

from app.core.db import Pool, tenant_transaction
from app.main import create_app


async def _create_org(pool: Pool, *, settings: dict[str, object] | None = None) -> str:
    org_id = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.organizations"
            " (id, slug, name, idp_organization_id, domain_key, settings)"
            " VALUES ($1, $2, 'Settings API Org', $3, 'generic', $4::jsonb)",
            org_id,
            f"settings-api-{org_id.hex[:12]}",
            f"idp-settings-api-{uuid4().hex[:12]}",
            json.dumps(settings or {}),
        )
    return str(org_id)


@pytest.fixture
async def client(make_pool: PoolFactory) -> AsyncIterator[httpx.AsyncClient]:
    pool = await make_pool("api")
    app = create_app()
    app.state.pool = pool
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _headers(org_id: str, role: str = "admin") -> dict[str, str]:
    return {"x-member-id": str(uuid4()), "x-organization-id": org_id, "x-role": role}


async def test_get_requires_permission(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool, settings={"locale": "en-US"})
    res = await client.get("/api/v1/organizations/settings", headers=_headers(org_id, role="member"))
    assert res.status_code == 404


async def test_get_returns_current_settings(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool, settings={"locale": "en-US", "currency": "USD"})
    res = await client.get("/api/v1/organizations/settings", headers=_headers(org_id))
    assert res.status_code == 200
    assert res.json()["data"] == {"locale": "en-US", "currency": "USD"}


async def test_patch_requires_permission(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    res = await client.patch(
        "/api/v1/organizations/settings", json={"locale": "fr-FR"}, headers=_headers(org_id, role="member")
    )
    assert res.status_code == 403  # a write, not a read: master plan §C4.5


async def test_patch_updates_and_is_audited(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool, settings={"locale": "en-US"})
    res = await client.patch(
        "/api/v1/organizations/settings",
        json={"locale": "de-DE", "timezone": "Europe/Berlin"},
        headers=_headers(org_id),
    )
    assert res.status_code == 200
    assert res.json()["data"] == {"locale": "de-DE", "timezone": "Europe/Berlin"}

    async with tenant_transaction(pool, UUID(org_id)) as conn:
        action = await conn.fetchval(
            "SELECT action FROM public.audit_events"
            " WHERE organization_id = $1 AND entity_type = 'organization'",
            UUID(org_id),
        )
    assert action == "organization.settings_update"


async def test_patch_rejects_an_invalid_body(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    res = await client.patch(
        "/api/v1/organizations/settings", json={"provisioning": "not-a-policy"}, headers=_headers(org_id)
    )
    assert res.status_code == 422


async def test_patch_rejects_an_unknown_field(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    res = await client.patch(
        "/api/v1/organizations/settings", json={"made_up": "x"}, headers=_headers(org_id)
    )
    assert res.status_code == 422


async def test_requests_without_a_member_are_unauthorized(client: httpx.AsyncClient) -> None:
    res = await client.get("/api/v1/organizations/settings")
    assert res.status_code == 401
