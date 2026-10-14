# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Saved asset views API: per-member ownership, validation, audit and outbox, and "a view never
widens access" (§B8.1, M2.1-T5, P8-07 step 7)."""

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

BASE = "/api/v1/asset-saved-views"


class _Registry:
    def __init__(self, secrets: FileSecretsProvider) -> None:
        self.auth = MockAuthProvider(ProviderContext("test", "auth", Path()))
        self.telemetry = NoOpTelemetryProvider()
        self.secrets = secrets


@pytest.fixture
async def client(make_pool: PoolFactory, tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    secrets = FileSecretsProvider.from_settings(
        {"directory": "secrets"}, ProviderContext(env="test", pillar="secrets", base_dir=tmp_path)
    )
    app = create_app()
    app.state.pool = await make_pool("api")
    app.state.registry = _Registry(secrets)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _create_org(pool: Pool) -> UUID:
    org_id = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.organizations"
            " (id, slug, name, idp_organization_id, domain_key, settings)"
            " VALUES ($1, $2, 'Views Org', $3, 'it-assets', '{}'::jsonb)",
            org_id,
            f"views-{org_id.hex[:12]}",
            f"idp-views-{uuid4().hex[:12]}",
        )
        await install_module(conn, org_id, "assets")
    return org_id


async def _member(pool: Pool, org_id: UUID, role: str = "admin") -> dict[str, str]:
    member_id = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.members (id, organization_id, idp_subject, email, display_name, status) "
            "VALUES ($1, $2, $3, $4, 'Viewer', 'active')",
            member_id,
            org_id,
            f"idp-{member_id.hex[:12]}",
            f"{member_id.hex[:12]}@example.test",
        )
    return {"x-member-id": str(member_id), "x-organization-id": str(org_id), "x-role": role}


async def test_create_list_edit_delete_own_view(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    headers = await _member(pool, org_id)

    created = await client.post(
        BASE,
        json={
            "name": "High criticality",
            "query": {"criticality": ["high"], "q": "laptop", "cf.ram_gb.gte": 16},
            "sort": "-updated_at",
            "columns": ["tag", "name"],
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    view = created.json()["data"]
    assert view["version"] == 1
    assert view["query"]["criticality"] == ["high"]

    listed = await client.get(BASE, headers=headers)
    assert [v["id"] for v in listed.json()["data"]["items"]] == [view["id"]]

    edited = await client.patch(
        f"{BASE}/{view['id']}", json={"version": 1, "name": "Renamed", "columns": ["tag"]}, headers=headers
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["data"]["name"] == "Renamed"
    assert edited.json()["data"]["version"] == 2
    assert edited.json()["data"]["query"] == view["query"]

    stale = await client.patch(f"{BASE}/{view['id']}", json={"version": 1, "name": "x"}, headers=headers)
    assert stale.status_code == 409
    assert stale.json()["code"] == "asset_saved_view.version_conflict"

    deleted = await client.delete(f"{BASE}/{view['id']}", headers=headers)
    assert deleted.status_code == 200
    assert (await client.get(BASE, headers=headers)).json()["data"]["items"] == []


async def test_views_are_private_to_the_member(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    owner = await _member(pool, org_id)
    other = await _member(pool, org_id)
    created = await client.post(BASE, json={"name": "Mine"}, headers=owner)
    view_id = created.json()["data"]["id"]

    assert (await client.get(BASE, headers=other)).json()["data"]["items"] == []
    patch = await client.patch(f"{BASE}/{view_id}", json={"version": 1, "name": "Taken"}, headers=other)
    assert patch.status_code == 404
    assert patch.json()["code"] == "asset_saved_view.not_found"
    assert (await client.delete(f"{BASE}/{view_id}", headers=other)).status_code == 404
    # the same name is free for another member
    assert (await client.post(BASE, json={"name": "Mine"}, headers=other)).status_code == 201


async def test_other_organization_cannot_touch_a_view(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_a, org_b = await _create_org(pool), await _create_org(pool)
    owner = await _member(pool, org_a)
    outsider = await _member(pool, org_b)
    view_id = (await client.post(BASE, json={"name": "Mine"}, headers=owner)).json()["data"]["id"]

    assert (await client.get(BASE, headers=outsider)).json()["data"]["items"] == []
    patched = await client.patch(f"{BASE}/{view_id}", json={"version": 1}, headers=outsider)
    assert patched.status_code == 404
    assert (await client.delete(f"{BASE}/{view_id}", headers=outsider)).status_code == 404


async def test_duplicate_name_and_invalid_content_are_refused(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    headers = await _member(pool, org_id)
    assert (await client.post(BASE, json={"name": "A"}, headers=headers)).status_code == 201
    duplicate = await client.post(BASE, json={"name": "A"}, headers=headers)
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "asset_saved_view.name_conflict"

    for body in (
        {"name": "B", "sort": "password"},
        {"name": "B", "columns": ["notes"]},
        {"name": "B", "query": {"drop_table": "x"}},
        {"name": "B", "query": {"status": [{"nested": 1}]}},
        {"name": "  "},
    ):
        res = await client.post(BASE, json=body, headers=headers)
        assert res.status_code == 422, (body, res.text)


async def test_writes_audit_and_outbox(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    headers = await _member(pool, org_id)
    view_id = (await client.post(BASE, json={"name": "A"}, headers=headers)).json()["data"]["id"]
    await client.patch(f"{BASE}/{view_id}", json={"version": 1, "name": "B"}, headers=headers)
    await client.delete(f"{BASE}/{view_id}", headers=headers)

    async with tenant_transaction(pool, org_id) as conn:
        actions = await conn.fetch(
            "SELECT action FROM public.audit_events WHERE entity_type = 'asset_saved_view' "
            "ORDER BY created_at"
        )
        events = await conn.fetch(
            "SELECT event_type FROM public.outbox WHERE aggregate_type = 'asset_saved_view' "
            "ORDER BY created_at"
        )
    assert [r["action"] for r in actions] == [
        "asset_saved_view.create",
        "asset_saved_view.update",
        "asset_saved_view.delete",
    ]
    assert [r["event_type"] for r in events] == [
        "asset_saved_view.created",
        "asset_saved_view.updated",
        "asset_saved_view.deleted",
    ]


async def test_applying_a_view_never_widens_access(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    """A view only stores a query; the member list still runs through their own scope, so a view
    naming another unit id returns nothing for a member who has no access there."""
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    owner = await _member(pool, org_id)
    other_unit, category = uuid4(), uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.org_units (id, organization_id, parent_id, path, type, code, name) "
            "VALUES ($1, $2, NULL, 'secret', 'unit', 'secret', 'secret')",
            other_unit,
            org_id,
        )
        await conn.execute(
            "INSERT INTO public.asset_categories (id, organization_id, parent_id, path, code, name) "
            "VALUES ($1, $2, NULL, 'cat', 'cat', 'cat')",
            category,
            org_id,
        )
    asset = await client.post(
        "/api/v1/assets",
        json={"name": "Hidden", "category_id": str(category), "owner_org_unit_id": str(other_unit)},
        headers=owner,
    )
    assert asset.status_code == 201, asset.text

    restricted = {
        **owner,
        "x-scope-type": "org_unit",
        "x-org-unit-path": "elsewhere",
        "x-role": "asset_manager",
    }
    view = await client.post(
        BASE,
        json={"name": "Secret unit", "query": {"owner_org_unit_id": str(other_unit)}},
        headers=restricted,
    )
    assert view.status_code == 201, view.text
    applied = await client.get(
        "/api/v1/assets", params={"owner_org_unit_id": str(other_unit)}, headers=restricted
    )
    assert applied.status_code == 200
    assert applied.json()["data"]["items"] == []
