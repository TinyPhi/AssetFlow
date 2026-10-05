# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Asset list API: filters, sort, cursor pagination, fuzzy search, custom-field filters (§B8.1,
§B5.3, §B4.5, M2.1-T5, P8-07 part b)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from pg_harness import PoolFactory

from app.core.db import Pool, tenant_transaction
from app.main import create_app
from app.modules.organization.modules import install_module
from app.providers.auth.mock import MockAuthProvider
from app.providers.context import ProviderContext
from app.providers.secrets.file import FileSecretsProvider
from app.providers.telemetry.noop import NoOpTelemetryProvider

BASE = "/api/v1/assets"


class _Registry:
    def __init__(self, secrets: FileSecretsProvider) -> None:
        self.auth = MockAuthProvider(ProviderContext("test", "auth", Path()))
        self.telemetry = NoOpTelemetryProvider()
        self.secrets = secrets


@pytest.fixture
def secrets_provider(tmp_path: Path) -> FileSecretsProvider:
    context = ProviderContext(env="test", pillar="secrets", base_dir=tmp_path)
    return FileSecretsProvider.from_settings({"directory": "secrets"}, context)


@pytest.fixture
async def client(
    make_pool: PoolFactory, secrets_provider: FileSecretsProvider
) -> AsyncIterator[httpx.AsyncClient]:
    pool = await make_pool("api")
    app = create_app()
    app.state.pool = pool
    app.state.registry = _Registry(secrets_provider)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _token() -> str:
    return uuid4().hex[:10]


def _headers(org_id: UUID, role: str = "admin") -> dict[str, str]:
    return {"x-member-id": str(uuid4()), "x-organization-id": str(org_id), "x-role": role}


async def _create_org(pool: Pool) -> UUID:
    org_id = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.organizations"
            " (id, slug, name, idp_organization_id, domain_key, settings)"
            " VALUES ($1, $2, 'Assets List Org', $3, 'it-assets', '{}'::jsonb)",
            org_id,
            f"assets-list-{org_id.hex[:12]}",
            f"idp-assets-list-{uuid4().hex[:12]}",
        )
        await install_module(conn, org_id, "assets")
    return org_id


async def _make_org_unit(pool: Pool, org_id: UUID) -> UUID:
    unit_id = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.org_units (id, organization_id, parent_id, path, type, code, name) "
            "VALUES ($1, $2, NULL, $3::ltree, 'unit', $3, $3)",
            unit_id,
            org_id,
            _token(),
        )
    return unit_id


async def _make_category(pool: Pool, org_id: UUID, *, default_criticality: str | None = None) -> UUID:
    category_id = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.asset_categories "
            "(id, organization_id, parent_id, path, code, name, default_criticality) "
            "VALUES ($1, $2, NULL, $3::ltree, $3, $3, $4)",
            category_id,
            org_id,
            _token(),
            default_criticality,
        )
    return category_id


async def _create_asset(
    client: httpx.AsyncClient,
    org_id: UUID,
    unit_id: UUID,
    category_id: UUID,
    *,
    name: str = "Laptop",
    criticality: str | None = None,
    custom_fields: dict[str, object] | None = None,
) -> str:
    body: dict[str, object] = {
        "name": name,
        "category_id": str(category_id),
        "owner_org_unit_id": str(unit_id),
    }
    if criticality is not None:
        body["criticality"] = criticality
    if custom_fields is not None:
        body["custom_fields"] = custom_fields
    res = await client.post(BASE, json=body, headers=_headers(org_id))
    assert res.status_code == 201, res.text
    return str(res.json()["data"]["id"])


async def test_filter_by_status_and_criticality(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    unit_id = await _make_org_unit(pool, org_id)
    category_id = await _make_category(pool, org_id)
    low_id = await _create_asset(client, org_id, unit_id, category_id, name="Low", criticality="low")
    await _create_asset(client, org_id, unit_id, category_id, name="High", criticality="high")

    res = await client.get(BASE, params={"criticality": "low"}, headers=_headers(org_id))
    assert res.status_code == 200
    ids = [item["id"] for item in res.json()["data"]["items"]]
    assert ids == [low_id]


async def test_filter_by_category_with_subcategories(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    unit_id = await _make_org_unit(pool, org_id)
    parent_id = await _make_category(pool, org_id)
    child_id = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        parent_path = await conn.fetchval(
            "SELECT path::text FROM public.asset_categories WHERE id = $1", parent_id
        )
        await conn.execute(
            "INSERT INTO public.asset_categories "
            "(id, organization_id, parent_id, path, code, name) VALUES ($1, $2, $3, $4::ltree, $5, $5)",
            child_id,
            org_id,
            parent_id,
            f"{parent_path}.{_token()}",
            _token(),
        )
    asset_id = await _create_asset(client, org_id, unit_id, child_id)

    narrow = await client.get(BASE, params={"category_id": str(parent_id)}, headers=_headers(org_id))
    assert narrow.json()["data"]["items"] == []

    wide = await client.get(
        BASE,
        params={"category_id": str(parent_id), "include_subcategories": "true"},
        headers=_headers(org_id),
    )
    ids = [item["id"] for item in wide.json()["data"]["items"]]
    assert ids == [asset_id]


async def test_sort_is_stable_across_cursor_pages(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    unit_id = await _make_org_unit(pool, org_id)
    category_id = await _make_category(pool, org_id)
    created_ids = [
        await _create_asset(client, org_id, unit_id, category_id, name=f"Asset {i}") for i in range(5)
    ]

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(5):
        params = {"sort": "name", "limit": 2}
        if cursor:
            params["after"] = cursor
        res = await client.get(BASE, params=params, headers=_headers(org_id))
        assert res.status_code == 200
        page = res.json()["data"]
        seen.extend(item["id"] for item in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert seen == created_ids
    assert len(seen) == len(set(seen)) == 5


async def test_fuzzy_search_ranks_closer_matches_first(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    unit_id = await _make_org_unit(pool, org_id)
    category_id = await _make_category(pool, org_id)
    exact_id = await _create_asset(client, org_id, unit_id, category_id, name="ThinkPad X1 Carbon")
    await _create_asset(client, org_id, unit_id, category_id, name="Completely unrelated item")

    res = await client.get(BASE, params={"q": "ThinkPad"}, headers=_headers(org_id))
    assert res.status_code == 200
    items = res.json()["data"]["items"]
    assert items[0]["id"] == exact_id


async def test_custom_field_filter(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    unit_id = await _make_org_unit(pool, org_id)
    category_id = await _make_category(pool, org_id)
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.custom_field_definitions "
            "(id, organization_id, category_id, key, label, field_type, status, version) "
            "VALUES ($1, $2, $3, 'ram_gb', 'RAM', 'number', 'active', 1)",
            uuid4(),
            org_id,
            category_id,
        )
    match_id = await _create_asset(
        client, org_id, unit_id, category_id, name="16GB", custom_fields={"ram_gb": 16}
    )
    await _create_asset(client, org_id, unit_id, category_id, name="8GB", custom_fields={"ram_gb": 8})

    res = await client.get(BASE, params={"cf.ram_gb": "16"}, headers=_headers(org_id))
    assert res.status_code == 200
    ids = [item["id"] for item in res.json()["data"]["items"]]
    assert ids == [match_id]

    gte_res = await client.get(BASE, params={"cf.ram_gb.gte": "10"}, headers=_headers(org_id))
    gte_ids = [item["id"] for item in gte_res.json()["data"]["items"]]
    assert gte_ids == [match_id]


async def test_encrypted_custom_field_filter_is_refused(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    await _make_org_unit(pool, org_id)
    category_id = await _make_category(pool, org_id)
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.custom_field_definitions "
            "(id, organization_id, category_id, key, label, field_type, is_encrypted, status, version) "
            "VALUES ($1, $2, $3, 'ssn', 'SSN', 'text', true, 'active', 1)",
            uuid4(),
            org_id,
            category_id,
        )

    res = await client.get(BASE, params={"cf.ssn": "123-45-6789"}, headers=_headers(org_id))
    assert res.status_code == 422
    assert res.json()["code"] == "validation.invalid_field"


async def test_updated_since_filter(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    unit_id = await _make_org_unit(pool, org_id)
    category_id = await _make_category(pool, org_id)
    await _create_asset(client, org_id, unit_id, category_id)

    far_future = "2999-01-01T00:00:00Z"
    res = await client.get(BASE, params={"updated_since": far_future}, headers=_headers(org_id))
    assert res.status_code == 200
    assert res.json()["data"]["items"] == []


async def test_include_total(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    unit_id = await _make_org_unit(pool, org_id)
    category_id = await _make_category(pool, org_id)
    await _create_asset(client, org_id, unit_id, category_id)
    await _create_asset(client, org_id, unit_id, category_id)

    res = await client.get(BASE, params={"include_total": "true"}, headers=_headers(org_id))
    assert res.json()["data"]["total"] == 2


# ==============================================================================
# More filters, every sort, fields, errors, holder display
# ==============================================================================


async def _post_asset(client: httpx.AsyncClient, org_id: UUID, body: dict[str, object]) -> str:
    res = await client.post(BASE, json=body, headers=_headers(org_id))
    assert res.status_code == 201, res.text
    return str(res.json()["data"]["id"])


async def _ids(
    client: httpx.AsyncClient, org_id: UUID, params: dict[str, str | int | list[str]] | None = None
) -> list[str]:
    res = await client.get(BASE, params=params, headers=_headers(org_id))
    assert res.status_code == 200, res.text
    return [item["id"] for item in res.json()["data"]["items"]]
