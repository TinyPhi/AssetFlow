# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Asset list API: filters, sort, cursor pagination, fuzzy search, custom-field filters (§B8.1,
§B5.3, §B4.5, M2.1-T5, P8-07 part b)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
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


async def _insert_member(pool: Pool, org_id: UUID, *, status: str = "active", name: str = "Holder") -> UUID:
    member_id = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.members (id, organization_id, idp_subject, email, display_name, status) "
            "VALUES ($1, $2, $3, $4, $5, $6)",
            member_id,
            org_id,
            f"idp-{member_id.hex[:12]}",
            f"{member_id.hex[:12]}@example.test",
            name,
            status,
        )
    return member_id


async def _hold(pool: Pool, org_id: UUID, asset_id: str, column: str, holder_id: UUID) -> None:
    assert column in ("holder_member_id", "holder_team_id", "holder_location_id")
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            f"UPDATE public.assets SET {column} = $1 WHERE organization_id = $2 AND id = $3",  # noqa: S608
            holder_id,
            org_id,
            UUID(asset_id),
        )


async def test_status_multi_and_status_category(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    unit_id = await _make_org_unit(pool, org_id)
    category_id = await _make_category(pool, org_id)
    first = await _create_asset(client, org_id, unit_id, category_id, name="A")
    second = await _create_asset(client, org_id, unit_id, category_id, name="B")
    statuses = await _template_statuses()
    ended_key = next(key for key, category in statuses.items() if category == "ended")
    live_key = (await client.get(f"{BASE}/{first}", headers=_headers(org_id))).json()["data"]["status"]
    assert statuses[live_key] != "ended"
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "UPDATE public.assets SET status = $3 WHERE organization_id = $1 AND id = $2",
            org_id,
            UUID(second),
            ended_key,
        )
    assert await _ids(client, org_id, {"status": [ended_key, "nope"]}) == [second]
    assert sorted(await _ids(client, org_id, {"status": [ended_key, live_key]})) == sorted([first, second])
    assert await _ids(client, org_id, {"status_category": "ended"}) == [second]
    assert await _ids(client, org_id, {"status_category": "ended", "status": live_key}) == []
    bad = await client.get(BASE, params={"status_category": "bogus"}, headers=_headers(org_id))
    assert bad.status_code == 422
    assert bad.json()["code"] == "validation.invalid_field"


_IT_ASSETS = Path(__file__).resolve().parents[3] / "config" / "domains" / "it-assets.yaml"


async def _template_statuses() -> dict[str, str]:
    from app.engines.automation.domain_template import load_domain_template  # noqa: PLC0415
    from app.modules.assets.config import parse_assets_section  # noqa: PLC0415

    template = load_domain_template(_IT_ASSETS)
    config = parse_assets_section((template.model_extra or {})["assets"])
    return {s.key: s.category for s in config.statuses}


async def test_owner_unit_location_holder_manufacturer_supplier_and_date_filters(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    parent_id = await _make_org_unit(pool, org_id)
    async with tenant_transaction(pool, org_id) as conn:
        parent_path = await conn.fetchval("SELECT path::text FROM public.org_units WHERE id = $1", parent_id)
        child_id = uuid4()
        await conn.execute(
            "INSERT INTO public.org_units (id, organization_id, parent_id, path, type, code, name) "
            "VALUES ($1, $2, $3, $4::ltree, 'unit', $5, $5)",
            child_id,
            org_id,
            parent_id,
            f"{parent_path}.{_token()}",
            _token(),
        )
        parent_loc, child_loc, mfr_id, sup_id = uuid4(), uuid4(), uuid4(), uuid4()
        await conn.execute(
            "INSERT INTO public.locations (id, organization_id, parent_id, path, type, code, name) "
            "VALUES ($1, $2, NULL, $3::ltree, 'site', $3, $3)",
            parent_loc,
            org_id,
            _token(),
        )
        loc_path = await conn.fetchval("SELECT path::text FROM public.locations WHERE id = $1", parent_loc)
        await conn.execute(
            "INSERT INTO public.locations (id, organization_id, parent_id, path, type, code, name) "
            "VALUES ($1, $2, $3, $4::ltree, 'room', 'child', 'child')",
            child_loc,
            org_id,
            parent_loc,
            f"{loc_path}.{_token()}",
        )
        await conn.execute(
            "INSERT INTO public.manufacturers (id, organization_id, name) VALUES ($1, $2, 'Maker')",
            mfr_id,
            org_id,
        )
        await conn.execute(
            "INSERT INTO public.suppliers (id, organization_id, name) VALUES ($1, $2, 'Vendor')",
            sup_id,
            org_id,
        )
    category_id = await _make_category(pool, org_id)
    in_parent = await _post_asset(
        client,
        org_id,
        {
            "name": "P",
            "category_id": str(category_id),
            "owner_org_unit_id": str(parent_id),
            "manufacturer_id": str(mfr_id),
            "supplier_id": str(sup_id),
            "purchase_date": "2024-01-10",
            "warranty_end": "2026-01-10",
        },
    )
    in_child = await _post_asset(
        client,
        org_id,
        {
            "name": "C",
            "category_id": str(category_id),
            "owner_org_unit_id": str(child_id),
            "location_id": str(child_loc),
            "purchase_date": "2025-06-01",
            "warranty_end": "2028-06-01",
        },
    )

    assert await _ids(client, org_id, {"owner_org_unit_id": str(parent_id)}) == [in_parent]
    wide = await _ids(client, org_id, {"owner_org_unit_id": str(parent_id), "include_sub_units": "true"})
    assert sorted(wide) == sorted([in_parent, in_child])

    assert await _ids(client, org_id, {"location_id": str(parent_loc)}) == []
    sub_locations = {"location_id": str(parent_loc), "include_sub_locations": "true"}
    assert await _ids(client, org_id, sub_locations) == [in_child]
    assert await _ids(client, org_id, {"manufacturer_id": str(mfr_id)}) == [in_parent]
    assert await _ids(client, org_id, {"supplier_id": str(sup_id)}) == [in_parent]
    assert await _ids(client, org_id, {"warranty_end_before": "2027-01-01"}) == [in_parent]
    assert await _ids(client, org_id, {"warranty_end_after": "2027-01-01"}) == [in_child]
    assert await _ids(client, org_id, {"purchase_date_before": "2025-01-01"}) == [in_parent]
    assert await _ids(client, org_id, {"purchase_date_after": "2025-01-01"}) == [in_child]


async def test_holder_filters(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    unit_id = await _make_org_unit(pool, org_id)
    category_id = await _make_category(pool, org_id)
    member_id = await _insert_member(pool, org_id)
    team_id = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.teams (id, organization_id, type, code, name) "
            "VALUES ($1, $2, 'team', $3, 'Crew')",
            team_id,
            org_id,
            _token(),
        )
    held_by_member = await _create_asset(client, org_id, unit_id, category_id, name="M")
    held_by_team = await _create_asset(client, org_id, unit_id, category_id, name="T")
    await _create_asset(client, org_id, unit_id, category_id, name="free")
    await _hold(pool, org_id, held_by_member, "holder_member_id", member_id)
    await _hold(pool, org_id, held_by_team, "holder_team_id", team_id)

    assert await _ids(client, org_id, {"holder_type": "member"}) == [held_by_member]
    assert await _ids(client, org_id, {"holder_type": "team"}) == [held_by_team]
    assert await _ids(client, org_id, {"holder_member_id": str(member_id)}) == [held_by_member]
    assert await _ids(client, org_id, {"holder_team_id": str(team_id)}) == [held_by_team]
    bad = await client.get(BASE, params={"holder_type": "robot"}, headers=_headers(org_id))
    assert bad.status_code == 422


@pytest.mark.parametrize(
    "sort",
    [
        "tag",
        "-tag",
        "name",
        "-name",
        "status",
        "-status",
        "created_at",
        "-created_at",
        "updated_at",
        "-updated_at",
        "warranty_end",
        "-warranty_end",
        "purchase_date",
        "-purchase_date",
    ],
)
async def test_every_sort_pages_stably(client: httpx.AsyncClient, make_pool: PoolFactory, sort: str) -> None:
    """Paging with a small limit yields exactly the single-page order: no gap, no repeat, with
    ties (same status) and NULL warranty/purchase dates included."""
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    unit_id = await _make_org_unit(pool, org_id)
    category_id = await _make_category(pool, org_id)
    for index in range(7):
        body: dict[str, object] = {
            "name": f"Item {index % 3}",
            "category_id": str(category_id),
            "owner_org_unit_id": str(unit_id),
        }
        if index % 2 == 0:
            body["warranty_end"] = f"202{index % 4}-05-0{1 + index % 3}"
            body["purchase_date"] = f"201{index % 5}-03-0{1 + index % 4}"
        await _post_asset(client, org_id, body)

    everything = await _ids(client, org_id, {"sort": sort, "limit": 200})
    assert len(everything) == len(set(everything)) == 7

    paged: list[str] = []
    cursor: str | None = None
    for _ in range(10):
        params: dict[str, str | int] = {"sort": sort, "limit": 3}
        if cursor:
            params["after"] = cursor
        res = await client.get(BASE, params=params, headers=_headers(org_id))
        assert res.status_code == 200, res.text
        page = res.json()["data"]
        paged.extend(item["id"] for item in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert paged == everything


async def test_no_empty_last_page_when_total_is_a_multiple_of_limit(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    unit_id = await _make_org_unit(pool, org_id)
    category_id = await _make_category(pool, org_id)
    for _ in range(4):
        await _create_asset(client, org_id, unit_id, category_id)
    first = (await client.get(BASE, params={"limit": 2}, headers=_headers(org_id))).json()["data"]
    assert first["next_cursor"] is not None
    second = (
        await client.get(BASE, params={"limit": 2, "after": first["next_cursor"]}, headers=_headers(org_id))
    ).json()["data"]
    assert len(second["items"]) == 2
    assert second["next_cursor"] is None


async def test_search_pages_by_rank_and_short_input_uses_prefix(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    unit_id = await _make_org_unit(pool, org_id)
    category_id = await _make_category(pool, org_id)
    for name in ("Printer alpha", "Printer beta", "Printer gamma", "Printers delta", "Zebra scanner"):
        await _create_asset(client, org_id, unit_id, category_id, name=name)

    everything = await _ids(client, org_id, {"q": "Printer", "limit": 200})
    assert len(everything) == 4
    paged: list[str] = []
    cursor: str | None = None
    for _ in range(5):
        params: dict[str, str | int] = {"q": "Printer", "limit": 2}
        if cursor:
            params["after"] = cursor
        page = (await client.get(BASE, params=params, headers=_headers(org_id))).json()["data"]
        paged.extend(item["id"] for item in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert paged == everything

    short = await client.get(BASE, params={"q": "Ze"}, headers=_headers(org_id))
    assert [i["name"] for i in short.json()["data"]["items"]] == ["Zebra scanner"]


async def test_fields_selection_and_unknown_field(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    unit_id = await _make_org_unit(pool, org_id)
    category_id = await _make_category(pool, org_id)
    await _create_asset(client, org_id, unit_id, category_id)
    res = await client.get(BASE, params={"fields": "tag,status"}, headers=_headers(org_id))
    assert res.status_code == 200
    assert set(res.json()["data"]["items"][0]) == {"id", "tag", "status"}
    bad = await client.get(BASE, params={"fields": "tag,notes"}, headers=_headers(org_id))
    assert bad.status_code == 422
    assert bad.json()["code"] == "validation.invalid_field"


async def test_invalid_sort_cursor_and_custom_field_filters_are_422(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    unit_id = await _make_org_unit(pool, org_id)
    category_id = await _make_category(pool, org_id)
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.custom_field_definitions "
            "(id, organization_id, category_id, key, label, field_type, status, version) "
            "VALUES ($1, $2, $3, 'color', 'Color', 'text', 'active', 1)",
            uuid4(),
            org_id,
            category_id,
        )
    await _create_asset(client, org_id, unit_id, category_id)
    injection = "cf.color'; DROP TABLE assets; --"
    for params in (
        {"sort": "password"},
        {"after": "not-a-cursor"},
        {"cf.unknown": "x"},
        {"cf.color.gte": "x"},  # range operators need a number or date field
        {injection: "x"},
    ):
        res = await client.get(BASE, params=params, headers=_headers(org_id))
        assert res.status_code == 422, (params, res.text)
        assert res.json()["code"] == "validation.invalid_field"


async def test_holder_display_names_come_from_one_batched_lookup(
    client: httpx.AsyncClient, make_pool: PoolFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.assets import service  # noqa: PLC0415

    pool = await make_pool("api")
    org_id = await _create_org(pool)
    unit_id = await _make_org_unit(pool, org_id)
    category_id = await _make_category(pool, org_id)
    active = await _insert_member(pool, org_id, name="Ada Active")
    departed = await _insert_member(pool, org_id, status="left", name="Dan Departed")
    asset_active = await _create_asset(client, org_id, unit_id, category_id, name="one")
    asset_departed = await _create_asset(client, org_id, unit_id, category_id, name="two")
    asset_third = await _create_asset(client, org_id, unit_id, category_id, name="three")
    await _hold(pool, org_id, asset_active, "holder_member_id", active)
    await _hold(pool, org_id, asset_departed, "holder_member_id", departed)
    await _hold(pool, org_id, asset_third, "holder_member_id", active)

    calls = 0
    original = service._asset_repo.departed_member_ids

    async def counting(*args: Any, **kwargs: Any) -> set[UUID]:
        nonlocal calls
        calls += 1
        return await original(*args, **kwargs)

    monkeypatch.setattr(service._asset_repo, "departed_member_ids", counting)
    res = await client.get(BASE, headers=_headers(org_id))
    assert res.status_code == 200
    by_id = {i["id"]: i for i in res.json()["data"]["items"]}
    assert by_id[asset_active]["holder"]["display_name"] == "Ada Active"
    assert by_id[asset_departed]["holder"]["display_name"] == "Former member"
    assert calls == 1
    assert "@example.test" not in res.text
