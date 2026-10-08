# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""M2.1 acceptance (master §B15 catalog rows, P8-12): one test per row, run for an organization on
each shipped domain template (`it-assets`, `facilities`), the first evidence for Gate G2's
two-template criterion.

Rows: "Asset catalog with search and filters" (trigram search, saved views, scopes), "Categories
and custom fields" (tree, seven types, validation, encrypted fields), "Components"
(move-with-parent), "Lifecycle statuses" (config-defined, workflow rules).

The whole API runs in process against a real disposable PostgreSQL (mock auth headers), the same
harness as the other e2e API flows. Components are covered in depth by
`test_asset_components_flow.py`; the test here proves the row on both templates.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import yaml
from pg_harness import PoolFactory

from app.core.db import Pool, tenant_transaction
from app.main import create_app
from app.modules.organization.modules import install_module
from app.providers.auth.mock import MockAuthProvider
from app.providers.context import ProviderContext
from app.providers.secrets.file import FileSecretsProvider
from app.providers.telemetry.noop import NoOpTelemetryProvider

BASE = "/api/v1/assets"
DOMAINS = Path(__file__).resolve().parents[3] / "config" / "domains"
TEMPLATES = ("it-assets", "facilities")
SEVEN_TYPES = ("text", "number", "date", "boolean", "select", "multi_select", "json")

pytestmark = pytest.mark.parametrize("domain_key", TEMPLATES)


class _Registry:
    def __init__(self, secrets: FileSecretsProvider) -> None:
        self.auth = MockAuthProvider(ProviderContext("test", "auth", Path()))
        self.telemetry = NoOpTelemetryProvider()
        self.secrets = secrets


@pytest.fixture
async def client(make_pool: PoolFactory, tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    (tmp_path / "file.key").write_bytes(os.urandom(32))  # the field-encryption key (test only)
    secrets = FileSecretsProvider(
        ProviderContext(env="test", pillar="secrets", base_dir=tmp_path),
        tmp_path,
        encryption_key_file="file.key",
    )
    app = create_app()
    app.state.pool = await make_pool("api")
    app.state.registry = _Registry(secrets)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _template(domain_key: str) -> dict[str, Any]:
    raw = yaml.safe_load((DOMAINS / f"{domain_key}.yaml").read_text(encoding="utf-8"))
    section: dict[str, Any] = raw["assets"]
    return section


def _headers(org_id: UUID, role: str = "admin", **scope: str) -> dict[str, str]:
    base = {"x-member-id": str(uuid4()), "x-organization-id": str(org_id), "x-role": role}
    return {**base, **{f"x-{k.replace('_', '-')}": v for k, v in scope.items()}}


class _World:
    """One organization on a template: a root org unit with two sibling children."""

    def __init__(self, pool: Pool, org_id: UUID, domain_key: str) -> None:
        self.pool = pool
        self.org_id = org_id
        self.domain_key = domain_key
        self.root_id = uuid4()
        self.root_path = f"r{uuid4().hex[:10]}"
        self.unit_a = uuid4()
        self.path_a = f"{self.root_path}.a{uuid4().hex[:8]}"
        self.unit_b = uuid4()
        self.path_b = f"{self.root_path}.b{uuid4().hex[:8]}"

    @classmethod
    async def create(cls, pool: Pool, domain_key: str) -> _World:
        org_id = uuid4()
        world = cls(pool, org_id, domain_key)
        async with tenant_transaction(pool, org_id) as conn:
            await conn.execute(
                "INSERT INTO public.organizations"
                " (id, slug, name, idp_organization_id, domain_key, settings)"
                " VALUES ($1, $2, 'M2.1 Acceptance Org', $3, $4, '{}'::jsonb)",
                org_id,
                f"m21-{org_id.hex[:12]}",
                f"idp-m21-{uuid4().hex[:12]}",
                domain_key,
            )
            await install_module(conn, org_id, "assets")
            insert = (
                "INSERT INTO public.org_units (id, organization_id, parent_id, path, type, code, name) "
                "VALUES ($1, $2, $3, $4::ltree, 'unit', $5, $5)"
            )
            await conn.execute(insert, world.root_id, org_id, None, world.root_path, world.root_path)
            await conn.execute(
                insert, world.unit_a, org_id, world.root_id, world.path_a, world.path_a.split(".")[-1]
            )
            await conn.execute(
                insert, world.unit_b, org_id, world.root_id, world.path_b, world.path_b.split(".")[-1]
            )
        return world

    def admin(self) -> dict[str, str]:
        return _headers(self.org_id)

    def unit_manager(self, path: str) -> dict[str, str]:
        return _headers(self.org_id, role="asset_manager", scope_type="org_unit", org_unit_path=path)


async def _post(client: httpx.AsyncClient, url: str, json: dict[str, Any], headers: dict[str, str]) -> Any:
    res = await client.post(url, json=json, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()["data"]


async def _category(client: httpx.AsyncClient, world: _World, code: str, **extra: Any) -> dict[str, Any]:
    data: dict[str, Any] = await _post(
        client, "/api/v1/asset-categories", {"code": code, "name": code.title(), **extra}, world.admin()
    )
    return data


async def _asset(
    client: httpx.AsyncClient,
    world: _World,
    category_id: str,
    unit: UUID,
    name: str,
    **extra: Any,
) -> dict[str, Any]:
    data: dict[str, Any] = await _post(
        client,
        BASE,
        {"name": name, "category_id": category_id, "owner_org_unit_id": str(unit), **extra},
        world.admin(),
    )
    return data


# ==============================================================================
# Row: Asset catalog with search and filters (trigram search, saved views, scopes)
# ==============================================================================


async def test_catalog_scopes_search_filters_views_and_cursor_pages(
    client: httpx.AsyncClient, make_pool: PoolFactory, domain_key: str
) -> None:
    world = await _World.create(await make_pool("api"), domain_key)
    category = await _category(client, world, "workstation")
    field = await client.post(
        f"/api/v1/asset-categories/{category['id']}/custom-fields",
        json={"key": "ram_gb", "label": "RAM (GB)", "field_type": "number", "min": 1, "max": 512},
        headers=world.admin(),
    )
    assert field.status_code == 201, field.text

    in_a = await _asset(
        client, world, category["id"], world.unit_a, "Latitude Workstation", custom_fields={"ram_gb": 32}
    )
    in_b = await _asset(
        client, world, category["id"], world.unit_b, "Precision Tower", custom_fields={"ram_gb": 8}
    )

    # Sibling-unit member: cannot list or open the other unit's assets.
    manager_a = world.unit_manager(world.path_a)
    listed = await client.get(BASE, headers=manager_a)
    assert listed.status_code == 200
    assert [i["id"] for i in listed.json()["data"]["items"]] == [in_a["id"]]
    assert (await client.get(f"{BASE}/{in_b['id']}", headers=manager_a)).status_code == 404
    assert (await client.get(f"{BASE}/{in_a['id']}", headers=manager_a)).status_code == 200

    # Parent-unit member: sees both.
    parent = await client.get(BASE, headers=world.unit_manager(world.root_path))
    assert {i["id"] for i in parent.json()["data"]["items"]} == {in_a["id"], in_b["id"]}

    # Fuzzy search finds a misspelled name.
    fuzzy = await client.get(BASE, params={"q": "Latitud Workstaton"}, headers=world.admin())
    assert in_a["id"] in [i["id"] for i in fuzzy.json()["data"]["items"]]
    assert in_b["id"] not in [i["id"] for i in fuzzy.json()["data"]["items"]]

    # Filter by a custom field.
    by_field = await client.get(BASE, params={"cf.ram_gb.gte": "16"}, headers=world.admin())
    assert [i["id"] for i in by_field.json()["data"]["items"]] == [in_a["id"]]

    # A saved view re-applies: its stored query, sent to the list, gives the same rows.
    # (A view belongs to a member, so this caller needs a member row.)
    mine = _headers(world.org_id)
    member_id = uuid4()
    async with tenant_transaction(world.pool, world.org_id) as conn:
        await conn.execute(
            "INSERT INTO public.members (id, organization_id, idp_subject, email, display_name, status) "
            "VALUES ($1, $2, $3, $4, 'Viewer', 'active')",
            member_id,
            world.org_id,
            f"idp-{member_id.hex[:12]}",
            f"{member_id.hex[:12]}@example.test",
        )
    mine["x-member-id"] = str(member_id)
    saved = (
        await client.post(
            "/api/v1/asset-saved-views",
            json={"name": "Big machines", "query": {"cf.ram_gb.gte": 16}},
            headers=mine,
        )
    ).json()["data"]
    reloaded = (await client.get("/api/v1/asset-saved-views", headers=mine)).json()["data"]["items"]
    assert [v["id"] for v in reloaded] == [saved["id"]]
    applied = await client.get(BASE, params=reloaded[0]["query"], headers=mine)
    assert [i["id"] for i in applied.json()["data"]["items"]] == [in_a["id"]]

    # Cursor pages are stable: no duplicates or gaps, even when a row is added between pages.
    for n in range(4):
        await _asset(client, world, category["id"], world.unit_a, f"Filler {n}")
    first = (await client.get(BASE, params={"limit": 2}, headers=world.admin())).json()["data"]
    await _asset(client, world, category["id"], world.unit_a, "Late arrival")
    seen = [i["id"] for i in first["items"]]
    cursor = first["next_cursor"]
    while cursor:
        page = (await client.get(BASE, params={"limit": 2, "after": cursor}, headers=world.admin())).json()[
            "data"
        ]
        seen.extend(i["id"] for i in page["items"])
        cursor = page["next_cursor"]
    assert len(seen) == len(set(seen))
    assert {in_a["id"], in_b["id"]} <= set(seen)
    assert len(seen) == 6  # the six assets that existed when paging began, newest first


# ==============================================================================
# Row: Categories and custom fields (tree, 7 types, validation, encrypted fields)
# ==============================================================================


def _definition(field_type: str, **extra: Any) -> dict[str, Any]:
    return {"key": f"f_{field_type}", "label": field_type, "field_type": field_type, **extra}


async def test_category_tree_seven_field_types_rules_and_encrypted_fields(
    client: httpx.AsyncClient, make_pool: PoolFactory, domain_key: str
) -> None:
    world = await _World.create(await make_pool("api"), domain_key)
    parent = await _category(client, world, "equipment")
    child = await _category(client, world, "sensor", parent_id=parent["id"])
    tree = await client.get("/api/v1/asset-categories", headers=world.admin())
    by_code = {c["code"]: c for c in tree.json()["data"]["items"]}
    assert by_code["sensor"]["parent_id"] == parent["id"]

    definitions = {
        "text": _definition("text", regex="^[A-Z]{2}-[0-9]+$", is_required=True),
        "number": _definition("number", min=1, max=100),
        "date": _definition("date"),
        "boolean": _definition("boolean"),
        "select": _definition("select", options=["red", "green"]),
        "multi_select": _definition("multi_select", options=["a", "b", "c"]),
        "json": _definition("json"),
    }
    for definition in definitions.values():
        await _post(
            client, f"/api/v1/asset-categories/{child['id']}/custom-fields", definition, world.admin()
        )
    await _post(
        client,
        f"/api/v1/asset-categories/{child['id']}/custom-fields",
        {"key": "licence_key", "label": "Licence key", "field_type": "text", "is_encrypted": True},
        world.admin(),
    )
    assert set(definitions) == set(SEVEN_TYPES)

    valid = {
        "f_text": "AB-12",
        "f_number": 42,
        "f_date": "2026-01-31",
        "f_boolean": True,
        "f_select": "green",
        "f_multi_select": ["a", "c"],
        "f_json": {"k": [1, 2]},
        "licence_key": "SECRET-LICENCE-123",
    }

    # Every rule is refused with a field error naming the field.
    refusals = {
        "f_text": "lower-1",  # regex
        "f_number": 1000,  # max
        "f_date": "31/01/2026",  # type
        "f_boolean": "yes",  # type
        "f_select": "blue",  # option
        "f_multi_select": ["a", "z"],  # option
        "f_json": "not json structure",  # type
    }
    for key, bad in refusals.items():
        res = await client.post(
            BASE,
            json={
                "name": "Bad",
                "category_id": child["id"],
                "owner_org_unit_id": str(world.unit_a),
                "custom_fields": {**valid, key: bad},
            },
            headers=world.admin(),
        )
        assert res.status_code == 422, (key, res.text)
        assert any(e["field"] == f"custom_fields.{key}" for e in res.json()["errors"]), (key, res.text)
    missing = await client.post(
        BASE,
        json={
            "name": "Bad",
            "category_id": child["id"],
            "owner_org_unit_id": str(world.unit_a),
            "custom_fields": {k: v for k, v in valid.items() if k != "f_text"},
        },
        headers=world.admin(),
    )
    assert missing.status_code == 422
    assert any(e["field"] == "custom_fields.f_text" for e in missing.json()["errors"])
    unknown = await client.post(
        BASE,
        json={
            "name": "Bad",
            "category_id": child["id"],
            "owner_org_unit_id": str(world.unit_a),
            "custom_fields": {**valid, "not_defined": 1},
        },
        headers=world.admin(),
    )
    assert unknown.status_code == 422

    # A valid asset: the encrypted field is absent from the list, presence-only without
    # `asset.read_sensitive`, revealed with it.
    asset = await _asset(client, world, child["id"], world.unit_a, "Sensor 1", custom_fields=valid)
    listing = await client.get(BASE, headers=world.admin())
    assert "SECRET-LICENCE-123" not in listing.text
    assert "licence_key" not in listing.json()["data"]["items"][0].get("custom_fields", {})
    plain = await client.get(f"{BASE}/{asset['id']}", headers=_headers(world.org_id, role="team_lead"))
    assert plain.status_code == 200
    assert "SECRET-LICENCE-123" not in plain.text
    assert plain.json()["data"]["encrypted_fields"] == {"licence_key": {"is_set": True}}
    revealed = await client.get(f"{BASE}/{asset['id']}", headers=world.admin())
    assert revealed.json()["data"]["encrypted_fields"] == {"licence_key": "SECRET-LICENCE-123"}
    served = revealed.json()["data"]["custom_fields"]["f_number"]
    assert served == 42
    assert type(served) is int  # a JSON number, not text


# ==============================================================================
# Row: Components (move-with-parent)
# ==============================================================================


async def test_components_attach_move_with_parent_detach(
    client: httpx.AsyncClient, make_pool: PoolFactory, domain_key: str
) -> None:
    world = await _World.create(await make_pool("api"), domain_key)
    category = await _category(client, world, "machine")
    parent = await _asset(client, world, category["id"], world.unit_a, "Server")
    child = await _asset(client, world, category["id"], world.unit_a, "Disk")

    attached = await client.post(
        f"{BASE}/{parent['id']}/components",
        json={"child_asset_id": child["id"], "version": parent["version"]},
        headers=world.admin(),
    )
    assert attached.status_code == 201, attached.text

    async def get(asset_id: str) -> dict[str, Any]:
        data: dict[str, Any] = (await client.get(f"{BASE}/{asset_id}", headers=world.admin())).json()["data"]
        return data

    now = await get(parent["id"])
    assert now["component_count"] == 1
    moved = await client.patch(
        f"{BASE}/{parent['id']}",
        json={"owner_org_unit_id": str(world.unit_b), "move_components": True, "version": now["version"]},
        headers=world.admin(),
    )
    assert moved.status_code == 200, moved.text
    assert (await get(child["id"]))["owner_org_unit_id"] == str(world.unit_b)

    detached = await client.post(
        f"{BASE}/{parent['id']}/components/{child['id']}/detach",
        json={"version": (await get(parent["id"]))["version"]},
        headers=world.admin(),
    )
    assert detached.status_code == 200, detached.text
    assert (await get(parent["id"]))["component_count"] == 0


# ==============================================================================
# Row: Lifecycle statuses (config-defined, with workflow rules)
# ==============================================================================


async def test_lifecycle_allowed_invalid_and_retire_rule(
    client: httpx.AsyncClient, make_pool: PoolFactory, domain_key: str
) -> None:
    template = _template(domain_key)
    world = await _World.create(await make_pool("api"), domain_key)
    category = await _category(client, world, "machine")
    asset = await _asset(client, world, category["id"], world.unit_a, "Unit 1")
    assert asset["status"] == template["initial"]

    initial = template["initial"]
    declared_from_initial = {t["to"] for t in template["transitions"] if t["from"] == initial}
    reachable_somewhere = {t["to"] for t in template["transitions"]}
    invalid_target = next(
        s["key"]
        for s in template["statuses"]
        if s["key"] not in declared_from_initial and s["key"] != initial and s["key"] in reachable_somewhere
    )
    allowed_target = sorted(declared_from_initial)[0]

    refused = await client.post(
        f"{BASE}/{asset['id']}/change-status",
        json={"to_status": invalid_target, "version": asset["version"], "reason": "test"},
        headers=world.admin(),
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "asset.invalid_transition"
    assert initial in refused.json()["detail"] and invalid_target in refused.json()["detail"]

    ok = await client.post(
        f"{BASE}/{asset['id']}/change-status",
        json={"to_status": allowed_target, "version": asset["version"]},
        headers=world.admin(),
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["status"] == allowed_target

    # "Cannot retire an assigned asset" is template data: every move into a final status carries
    # the `holder does not exist` condition (exercised end to end in P9-13 once custody exists).
    finals = {s["key"] for s in template["statuses"] if s.get("is_final")}
    into_final = [t for t in template["transitions"] if t["to"] in finals]
    assert into_final
    for transition in into_final:
        assert {"field": "holder", "operator": "exists", "value": False} in transition["conditions"]
        assert transition["requires_reason"] is True
