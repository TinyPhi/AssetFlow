# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Bulk import API: permission, preview-writes-nothing, commit-all-or-nothing (M1.4-T7)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import httpx
import pytest
from pg_harness import PoolFactory

from app.core.db import Pool, tenant_transaction
from app.main import create_app


async def _create_org(pool: Pool) -> str:
    org_id = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.organizations"
            " (id, slug, name, idp_organization_id, domain_key, settings)"
            " VALUES ($1, $2, 'Import API Org', $3, 'generic', $4::jsonb)",
            org_id,
            f"import-api-{org_id.hex[:12]}",
            f"idp-import-api-{uuid4().hex[:12]}",
            json.dumps({}),
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


_BODY = {"org_units": [{"code": "hq", "name": "Headquarters", "type": "division"}]}


async def test_preview_requires_permission(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    res = await client.post("/api/v1/import/preview", json=_BODY, headers=_headers(org_id, role="member"))
    assert res.status_code == 404


async def test_preview_writes_nothing(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    res = await client.post("/api/v1/import/preview", json=_BODY, headers=_headers(org_id))
    assert res.status_code == 200
    assert res.json()["data"]["org_units"] == {"created": 1, "skipped": 0}

    async with tenant_transaction(pool, UUID(org_id)) as conn:
        count = await conn.fetchval(
            "SELECT count(*) FROM public.org_units WHERE organization_id = $1", UUID(org_id)
        )
    assert count == 0


async def test_commit_writes_and_is_idempotent(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    first = await client.post("/api/v1/import/commit", json=_BODY, headers=_headers(org_id))
    assert first.status_code == 200
    assert first.json()["data"]["org_units"] == {"created": 1, "skipped": 0}

    second = await client.post("/api/v1/import/commit", json=_BODY, headers=_headers(org_id))
    assert second.status_code == 200
    assert second.json()["data"]["org_units"] == {"created": 0, "skipped": 1}


async def test_commit_rejects_an_invalid_row_with_a_field_level_report(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    bad_body = {
        "teams": [{"code": "t1", "name": "T1", "type": "maintenance", "owning_org_unit_code": "nope"}]
    }
    res = await client.post("/api/v1/import/commit", json=bad_body, headers=_headers(org_id))
    assert res.status_code == 422
    assert res.json()["errors"][0]["field"] == "teams[0].owning_org_unit_code"
