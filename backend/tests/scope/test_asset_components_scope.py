# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Scope handling for asset components (§B5.3, §C4.5, M2.1-T6, P8-09): a member who can edit the
parent but not one of its children cannot move with children (the whole move is refused, naming
the count, and nothing changes); a parent outside scope answers 404; a child outside the caller's
scope is left out of the component list."""

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


async def _setup(pool: Pool) -> tuple[UUID, dict[str, UUID], str, UUID]:
    """Organization with a root unit, two child units (`mine`, `theirs`) and `mine.sub`, a category.
    Returns the org id, the unit ids by name, the root path and the category id."""
    org_id, category_id = uuid4(), uuid4()
    root_path = f"r{uuid4().hex[:8]}"
    ids = {name: uuid4() for name in ("root", "mine", "theirs", "sub")}
    paths = {
        "root": root_path,
        "mine": f"{root_path}.mine",
        "theirs": f"{root_path}.theirs",
        "sub": f"{root_path}.mine.sub",
    }
    parents = {"root": None, "mine": ids["root"], "theirs": ids["root"], "sub": ids["mine"]}
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.organizations"
            " (id, slug, name, idp_organization_id, domain_key, settings)"
            " VALUES ($1, $2, 'Components Scope Org', $3, 'it-assets', '{}'::jsonb)",
            org_id,
            f"components-scope-{org_id.hex[:12]}",
            f"idp-components-scope-{uuid4().hex[:12]}",
        )
        await install_module(conn, org_id, "assets")
        for name in ("root", "mine", "theirs", "sub"):
            await conn.execute(
                "INSERT INTO public.org_units (id, organization_id, parent_id, path, type, code, name) "
                "VALUES ($1, $2, $3, $4::ltree, 'unit', $5, $5)",
                ids[name],
                org_id,
                parents[name],
                paths[name],
                name,
            )
        await conn.execute(
            "INSERT INTO public.asset_categories (id, organization_id, parent_id, path, code, name) "
            "VALUES ($1, $2, NULL, $3::ltree, $3, $3)",
            category_id,
            org_id,
            f"c{category_id.hex[:10]}",
        )
    return org_id, {**ids}, paths["mine"], category_id


def _admin(org_id: UUID) -> dict[str, str]:
    return {"x-member-id": str(uuid4()), "x-organization-id": str(org_id), "x-role": "admin"}


def _scoped(org_id: UUID, path: str) -> dict[str, str]:
    return {
        "x-member-id": str(uuid4()),
        "x-organization-id": str(org_id),
        "x-role": "asset_manager",
        "x-scope-type": "org_unit",
        "x-org-unit-path": path,
    }


async def _create(
    client: httpx.AsyncClient, org_id: UUID, unit_id: UUID, category_id: UUID
) -> dict[str, Any]:
    res = await client.post(
        BASE,
        json={"name": "Part", "category_id": str(category_id), "owner_org_unit_id": str(unit_id)},
        headers=_admin(org_id),
    )
    assert res.status_code == 201, res.text
    data: dict[str, Any] = res.json()["data"]
    return data


async def _attach(
    client: httpx.AsyncClient, org_id: UUID, parent: dict[str, Any], child: dict[str, Any]
) -> int:
    res = await client.post(
        f"{BASE}/{parent['id']}/components",
        json={"child_asset_id": child["id"], "version": parent["version"]},
        headers=_admin(org_id),
    )
    assert res.status_code == 201, res.text
    return int(res.json()["data"]["parent_version"])


async def test_move_with_children_is_refused_when_a_child_is_out_of_scope(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id, units, mine_path, category_id = await _setup(pool)
    parent = await _create(client, org_id, units["mine"], category_id)
    near = await _create(client, org_id, units["mine"], category_id)
    far = await _create(client, org_id, units["theirs"], category_id)
    version = await _attach(client, org_id, parent, near)
    version = await _attach(client, org_id, {**parent, "version": version}, far)

    res = await client.patch(
        f"{BASE}/{parent['id']}",
        json={"owner_org_unit_id": str(units["sub"]), "move_components": True, "version": version},
        headers=_scoped(org_id, mine_path),
    )
    assert res.status_code == 403, res.text
    body = res.json()
    assert body["code"] == "scope.denied"
    assert "1 record" in body["detail"]
    assert str(far["id"]) not in res.text

    # Nothing moved: not the parent, not the child inside scope.
    for asset in (parent, near):
        current = await client.get(f"{BASE}/{asset['id']}", headers=_admin(org_id))
        assert current.json()["data"]["owner_org_unit_id"] == str(units["mine"])

    # Without move_components the same edit is fine.
    plain = await client.patch(
        f"{BASE}/{parent['id']}",
        json={"owner_org_unit_id": str(units["sub"]), "version": version},
        headers=_scoped(org_id, mine_path),
    )
    assert plain.status_code == 200, plain.text


async def test_components_of_an_asset_outside_scope_answer_404(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id, units, mine_path, category_id = await _setup(pool)
    parent = await _create(client, org_id, units["theirs"], category_id)
    child = await _create(client, org_id, units["mine"], category_id)

    listed = await client.get(f"{BASE}/{parent['id']}/components", headers=_scoped(org_id, mine_path))
    assert listed.status_code == 404
    attach = await client.post(
        f"{BASE}/{parent['id']}/components",
        json={"child_asset_id": child["id"], "version": parent["version"]},
        headers=_scoped(org_id, mine_path),
    )
    assert attach.status_code == 404


async def test_child_outside_scope_is_hidden_from_the_list_and_the_detail_parent_is_omitted(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id, units, mine_path, category_id = await _setup(pool)
    parent = await _create(client, org_id, units["root"], category_id)
    near = await _create(client, org_id, units["mine"], category_id)
    far = await _create(client, org_id, units["theirs"], category_id)
    version = await _attach(client, org_id, parent, near)
    await _attach(client, org_id, {**parent, "version": version}, far)

    # A caller scoped to `mine` cannot read the parent (root unit) but can read `near`.
    detail = await client.get(f"{BASE}/{near['id']}", headers=_scoped(org_id, mine_path))
    assert detail.status_code == 200
    assert detail.json()["data"]["parent"] is None

    # A caller scoped to the root sees the parent, and both children.
    root_path = mine_path.split(".")[0]
    listed = await client.get(f"{BASE}/{parent['id']}/components", headers=_scoped(org_id, root_path))
    assert {i["child_asset_id"] for i in listed.json()["data"]["items"]} == {near["id"], far["id"]}
    seen = await client.get(f"{BASE}/{near['id']}", headers=_scoped(org_id, root_path))
    assert seen.json()["data"]["parent"]["id"] == parent["id"]
