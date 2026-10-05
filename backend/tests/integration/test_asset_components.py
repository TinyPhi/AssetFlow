# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Asset components (M2.1-T6, §B8.1, P8-09), against a real disposable PostgreSQL: attach, detach,
cycle refused, a second parent refused, an ended child refused, version conflicts, audit and
outbox rows for both assets, detail `parent` / `component_count`, and the list with history."""

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


async def _setup(pool: Pool) -> tuple[UUID, UUID, UUID]:
    """An organization with the assets module, one org unit and one category."""
    org_id, unit_id, category_id = uuid4(), uuid4(), uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.organizations"
            " (id, slug, name, idp_organization_id, domain_key, settings)"
            " VALUES ($1, $2, 'Components Org', $3, 'it-assets', '{}'::jsonb)",
            org_id,
            f"components-{org_id.hex[:12]}",
            f"idp-components-{uuid4().hex[:12]}",
        )
        await install_module(conn, org_id, "assets")
        await conn.execute(
            "INSERT INTO public.org_units (id, organization_id, parent_id, path, type, code, name) "
            "VALUES ($1, $2, NULL, $3::ltree, 'unit', $3, $3)",
            unit_id,
            org_id,
            _token(),
        )
        await conn.execute(
            "INSERT INTO public.asset_categories (id, organization_id, parent_id, path, code, name) "
            "VALUES ($1, $2, NULL, $3::ltree, $3, $3)",
            category_id,
            org_id,
            _token(),
        )
    return org_id, unit_id, category_id


def _headers(org_id: UUID) -> dict[str, str]:
    return {"x-member-id": str(uuid4()), "x-organization-id": str(org_id), "x-role": "admin"}


async def _asset(client: httpx.AsyncClient, org_id: UUID, unit_id: UUID, category_id: UUID) -> dict[str, Any]:
    res = await client.post(
        BASE,
        json={"name": "Part", "category_id": str(category_id), "owner_org_unit_id": str(unit_id)},
        headers=_headers(org_id),
    )
    assert res.status_code == 201, res.text
    data: dict[str, Any] = res.json()["data"]
    return data


async def _detail(client: httpx.AsyncClient, org_id: UUID, asset_id: str) -> dict[str, Any]:
    res = await client.get(f"{BASE}/{asset_id}", headers=_headers(org_id))
    assert res.status_code == 200, res.text
    data: dict[str, Any] = res.json()["data"]
    return data


async def _attach(
    client: httpx.AsyncClient, org_id: UUID, parent: str, child: str, version: int
) -> httpx.Response:
    return await client.post(
        f"{BASE}/{parent}/components",
        json={"child_asset_id": child, "version": version},
        headers=_headers(org_id),
    )


async def _pair(
    client: httpx.AsyncClient, pool: Pool
) -> tuple[UUID, UUID, UUID, dict[str, Any], dict[str, Any]]:
    org_id, unit_id, category_id = await _setup(pool)
    parent = await _asset(client, org_id, unit_id, category_id)
    child = await _asset(client, org_id, unit_id, category_id)
    return org_id, unit_id, category_id, parent, child


async def test_attach_links_the_child_and_bumps_both_versions(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id, _unit, _cat, parent, child = await _pair(client, pool)

    res = await _attach(client, org_id, parent["id"], child["id"], parent["version"])
    assert res.status_code == 201, res.text
    link = res.json()["data"]
    assert link["parent_version"] == parent["version"] + 1
    assert link["child_version"] == child["version"] + 1
    assert link["detached_at"] is None

    parent_after = await _detail(client, org_id, parent["id"])
    child_after = await _detail(client, org_id, child["id"])
    assert parent_after["component_count"] == 1
    assert parent_after["parent"] is None
    assert child_after["parent"] == {"id": parent["id"], "tag": parent["tag"], "name": "Part"}
    assert child_after["component_count"] == 0


async def test_attach_audits_both_assets_and_writes_one_outbox_row(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id, _unit, _cat, parent, child = await _pair(client, pool)
    assert (await _attach(client, org_id, parent["id"], child["id"], parent["version"])).status_code == 201

    async with tenant_transaction(pool, org_id) as conn:
        audited = {
            r["entity_id"]
            for r in await conn.fetch(
                "SELECT entity_id FROM public.audit_events "
                "WHERE organization_id = $1 AND action = 'asset.component_attached'",
                org_id,
            )
        }
        outbox = await conn.fetch(
            "SELECT aggregate_id, payload FROM public.outbox "
            "WHERE organization_id = $1 AND event_type = 'asset.component_attached'",
            org_id,
        )
    assert audited == {UUID(parent["id"]), UUID(child["id"])}
    assert len(outbox) == 1
    assert outbox[0]["aggregate_id"] == UUID(parent["id"])


async def test_detach_ends_the_link_and_keeps_history(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id, _unit, _cat, parent, child = await _pair(client, pool)
    link = (await _attach(client, org_id, parent["id"], child["id"], parent["version"])).json()["data"]

    res = await client.post(
        f"{BASE}/{parent['id']}/components/{child['id']}/detach",
        json={"version": link["parent_version"]},
        headers=_headers(org_id),
    )
    assert res.status_code == 200, res.text
    assert res.json()["data"]["detached_at"] is not None

    assert (await _detail(client, org_id, child["id"]))["parent"] is None
    assert (await _detail(client, org_id, parent["id"]))["component_count"] == 0

    current = await client.get(f"{BASE}/{parent['id']}/components", headers=_headers(org_id))
    assert current.json()["data"]["items"] == []
    history = await client.get(
        f"{BASE}/{parent['id']}/components", params={"include_history": "true"}, headers=_headers(org_id)
    )
    items = history.json()["data"]["items"]
    assert [i["child_asset_id"] for i in items] == [child["id"]]
    assert items[0]["detached_at"] is not None

    async with tenant_transaction(pool, org_id) as conn:
        actions = await conn.fetchval(
            "SELECT count(*) FROM public.audit_events "
            "WHERE organization_id = $1 AND action = 'asset.component_detached'",
            org_id,
        )
        events = await conn.fetchval(
            "SELECT count(*) FROM public.outbox "
            "WHERE organization_id = $1 AND event_type = 'asset.component_detached'",
            org_id,
        )
    assert (actions, events) == (2, 1)


async def test_detach_of_a_child_that_is_not_attached_is_404(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id, _unit, _cat, parent, child = await _pair(client, pool)
    res = await client.post(
        f"{BASE}/{parent['id']}/components/{child['id']}/detach",
        json={"version": parent["version"]},
        headers=_headers(org_id),
    )
    assert res.status_code == 404
    assert res.json()["code"] == "asset_component.not_attached"


async def test_cycle_is_refused(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id, unit_id, category_id = await _setup(pool)
    a = await _asset(client, org_id, unit_id, category_id)
    b = await _asset(client, org_id, unit_id, category_id)
    c = await _asset(client, org_id, unit_id, category_id)
    ab = (await _attach(client, org_id, a["id"], b["id"], a["version"])).json()["data"]
    bc = (await _attach(client, org_id, b["id"], c["id"], ab["child_version"])).json()["data"]

    # C is a grandchild of A: attaching A under C would close a loop.
    a_now = (await _detail(client, org_id, a["id"]))["version"]
    res = await _attach(client, org_id, c["id"], a["id"], bc["child_version"])
    assert res.status_code == 409
    assert res.json()["code"] == "asset_component.cycle"
    assert a_now == ab["parent_version"]

    # An asset cannot be its own component either.
    own = await _attach(client, org_id, a["id"], a["id"], a_now)
    assert own.status_code == 409
    assert own.json()["code"] == "asset_component.cycle"


async def test_second_parent_is_refused(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id, unit_id, category_id, parent, child = await _pair(client, pool)
    other = await _asset(client, org_id, unit_id, category_id)
    assert (await _attach(client, org_id, parent["id"], child["id"], parent["version"])).status_code == 201

    res = await _attach(client, org_id, other["id"], child["id"], other["version"])
    assert res.status_code == 409
    assert res.json()["code"] == "asset_component.already_attached"


async def test_ended_child_is_refused(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id, _unit, _cat, parent, child = await _pair(client, pool)
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "UPDATE public.assets SET status = 'retired' WHERE organization_id = $1 AND id = $2",
            org_id,
            UUID(child["id"]),
        )

    res = await _attach(client, org_id, parent["id"], child["id"], parent["version"])
    assert res.status_code == 409
    assert res.json()["code"] == "asset_component.child_ended"


async def test_attach_does_not_change_status_or_holder(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id, _unit, _cat, parent, child = await _pair(client, pool)
    await _attach(client, org_id, parent["id"], child["id"], parent["version"])
    after = await _detail(client, org_id, child["id"])
    assert after["status"] == child["status"]
    assert after["holder"] == child["holder"]


async def test_stale_parent_version_conflicts(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id, _unit, _cat, parent, child = await _pair(client, pool)
    res = await _attach(client, org_id, parent["id"], child["id"], parent["version"] + 5)
    assert res.status_code == 409
    assert res.json()["code"] == "asset.version_conflict"

    ok = (await _attach(client, org_id, parent["id"], child["id"], parent["version"])).json()["data"]
    stale = await client.post(
        f"{BASE}/{parent['id']}/components/{child['id']}/detach",
        json={"version": parent["version"]},
        headers=_headers(org_id),
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "asset.version_conflict"
    assert ok["parent_version"] == parent["version"] + 1


async def test_unknown_child_is_422_and_unknown_parent_is_404(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id, _unit, _cat, parent, _child = await _pair(client, pool)
    missing_child = await _attach(client, org_id, parent["id"], str(uuid4()), parent["version"])
    assert missing_child.status_code == 422
    missing_parent = await _attach(client, org_id, str(uuid4()), parent["id"], 1)
    assert missing_parent.status_code == 404


async def test_member_without_update_permission_is_refused(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id, _unit, _cat, parent, child = await _pair(client, pool)
    headers = {**_headers(org_id), "x-role": "member"}
    res = await client.post(
        f"{BASE}/{parent['id']}/components",
        json={"child_asset_id": child["id"], "version": parent["version"]},
        headers=headers,
    )
    assert res.status_code == 403
