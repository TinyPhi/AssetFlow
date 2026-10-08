# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""API E2E (master M2.1-T6): create a parent and two children, attach them, move the parent with
`move_components=true` (both children follow, each audited and outboxed), detach one, move the
parent again (the detached child stays put)."""

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


async def _setup(pool: Pool) -> tuple[UUID, list[UUID], list[UUID], UUID]:
    """Organization, three org units, two locations, one category."""
    org_id, category_id = uuid4(), uuid4()
    units, locations = [uuid4() for _ in range(3)], [uuid4() for _ in range(2)]
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.organizations"
            " (id, slug, name, idp_organization_id, domain_key, settings)"
            " VALUES ($1, $2, 'Components Flow Org', $3, 'it-assets', '{}'::jsonb)",
            org_id,
            f"components-flow-{org_id.hex[:12]}",
            f"idp-components-flow-{uuid4().hex[:12]}",
        )
        await install_module(conn, org_id, "assets")
        for unit in units:
            await conn.execute(
                "INSERT INTO public.org_units (id, organization_id, parent_id, path, type, code, name) "
                "VALUES ($1, $2, NULL, $3::ltree, 'unit', $3, $3)",
                unit,
                org_id,
                f"u{unit.hex[:10]}",
            )
        for location in locations:
            await conn.execute(
                "INSERT INTO public.locations (id, organization_id, parent_id, path, type, code, name) "
                "VALUES ($1, $2, NULL, $3::ltree, 'site', $3, $3)",
                location,
                org_id,
                f"l{location.hex[:10]}",
            )
        await conn.execute(
            "INSERT INTO public.asset_categories (id, organization_id, parent_id, path, code, name) "
            "VALUES ($1, $2, NULL, $3::ltree, $3, $3)",
            category_id,
            org_id,
            f"c{category_id.hex[:10]}",
        )
    return org_id, units, locations, category_id


async def test_components_attach_move_with_parent_and_detach(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id, units, locations, category_id = await _setup(pool)
    headers = {"x-member-id": str(uuid4()), "x-organization-id": str(org_id), "x-role": "admin"}

    async def create(name: str) -> dict[str, Any]:
        res = await client.post(
            BASE,
            json={
                "name": name,
                "category_id": str(category_id),
                "owner_org_unit_id": str(units[0]),
                "location_id": str(locations[0]),
            },
            headers=headers,
        )
        assert res.status_code == 201, res.text
        data: dict[str, Any] = res.json()["data"]
        return data

    async def get(asset_id: str) -> dict[str, Any]:
        res = await client.get(f"{BASE}/{asset_id}", headers=headers)
        data: dict[str, Any] = res.json()["data"]
        return data

    parent, disk_a, disk_b = await create("Server"), await create("Disk A"), await create("Disk B")

    # Attach both children.
    first = await client.post(
        f"{BASE}/{parent['id']}/components",
        json={"child_asset_id": disk_a["id"], "version": parent["version"]},
        headers=headers,
    )
    assert first.status_code == 201, first.text
    second = await client.post(
        f"{BASE}/{parent['id']}/components",
        json={"child_asset_id": disk_b["id"], "version": first.json()["data"]["parent_version"]},
        headers=headers,
    )
    assert second.status_code == 201, second.text

    # Move the parent with its components.
    parent_now = await get(parent["id"])
    assert parent_now["component_count"] == 2
    moved = await client.patch(
        f"{BASE}/{parent['id']}",
        json={
            "owner_org_unit_id": str(units[1]),
            "location_id": str(locations[1]),
            "move_components": True,
            "version": parent_now["version"],
        },
        headers=headers,
    )
    assert moved.status_code == 200, moved.text
    for disk in (disk_a, disk_b):
        after = await get(disk["id"])
        assert after["owner_org_unit_id"] == str(units[1])
        assert after["location_id"] == str(locations[1])
        assert after["version"] > disk["version"] + 1  # attach bump, then the move

    async with tenant_transaction(pool, org_id) as conn:
        audited = {
            r["entity_id"]
            for r in await conn.fetch(
                "SELECT entity_id FROM public.audit_events "
                "WHERE organization_id = $1 AND action = 'asset.moved_with_parent'",
                org_id,
            )
        }
        outboxed = await conn.fetchval(
            "SELECT count(*) FROM public.outbox "
            "WHERE organization_id = $1 AND event_type = 'asset.moved_with_parent'",
            org_id,
        )
        parent_audit = await conn.fetchval(
            "SELECT count(*) FROM public.audit_events "
            "WHERE organization_id = $1 AND action = 'asset.update' AND entity_id = $2",
            org_id,
            UUID(parent["id"]),
        )
    assert audited == {UUID(disk_a["id"]), UUID(disk_b["id"])}
    assert outboxed == 2
    assert parent_audit == 1

    # Detach one, then move the parent again: the detached disk stays where it is.
    detach = await client.post(
        f"{BASE}/{parent['id']}/components/{disk_b['id']}/detach",
        json={"version": (await get(parent["id"]))["version"]},
        headers=headers,
    )
    assert detach.status_code == 200, detach.text
    parent_now = await get(parent["id"])
    again = await client.patch(
        f"{BASE}/{parent['id']}",
        json={"owner_org_unit_id": str(units[2]), "move_components": True, "version": parent_now["version"]},
        headers=headers,
    )
    assert again.status_code == 200, again.text
    assert (await get(disk_a["id"]))["owner_org_unit_id"] == str(units[2])
    stayed = await get(disk_b["id"])
    assert stayed["owner_org_unit_id"] == str(units[1])
    assert stayed["location_id"] == str(locations[1])

    # move_components=false leaves children where they are.
    third = await client.patch(
        f"{BASE}/{parent['id']}",
        json={"owner_org_unit_id": str(units[0]), "version": (await get(parent["id"]))["version"]},
        headers=headers,
    )
    assert third.status_code == 200, third.text
    assert (await get(disk_a["id"]))["owner_org_unit_id"] == str(units[2])
