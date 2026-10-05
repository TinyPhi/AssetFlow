# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Scope handling for the asset API (§B5.3, M2.1-T5, P8-07): create/edit/detail (sibling org units,
parent-unit manager, self scope, revoked grant) and list (sibling org units in one call, team-holder
visibility, an asset matching two scope branches appears once, revoked grant stops at the next
list request)."""

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


_INSERT_ORG_UNIT = (
    "INSERT INTO public.org_units (id, organization_id, parent_id, path, type, code, name) "
    "VALUES ($1, $2, $3, $4::ltree, 'unit', $5, $5)"
)
_INSERT_CATEGORY = (
    "INSERT INTO public.asset_categories (id, organization_id, parent_id, path, code, name) "
    "VALUES ($1, $2, NULL, $3::ltree, $3, $3)"
)


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


async def _create_org(pool: Pool) -> UUID:
    org_id = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.organizations"
            " (id, slug, name, idp_organization_id, domain_key, settings)"
            " VALUES ($1, $2, 'Assets Scope Org', $3, 'it-assets', '{}'::jsonb)",
            org_id,
            f"assets-scope-{org_id.hex[:12]}",
            f"idp-assets-scope-{uuid4().hex[:12]}",
        )
        await install_module(conn, org_id, "assets")
    return org_id


async def _make_org_unit(
    pool: Pool, org_id: UUID, *, parent_id: UUID | None = None, parent_path: str = ""
) -> tuple[UUID, str]:
    unit_id = uuid4()
    code = _token()
    path = f"{parent_path}.{code}" if parent_path else code
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(_INSERT_ORG_UNIT, unit_id, org_id, parent_id, path, code)
    return unit_id, path


async def _make_category(pool: Pool, org_id: UUID) -> UUID:
    category_id = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(_INSERT_CATEGORY, category_id, org_id, _token())
    return category_id


async def _create_asset(client: httpx.AsyncClient, org_id: UUID, unit_id: UUID, category_id: UUID) -> str:
    res = await client.post(
        BASE,
        json={"name": "Laptop 1", "category_id": str(category_id), "owner_org_unit_id": str(unit_id)},
        headers={"x-member-id": str(uuid4()), "x-organization-id": str(org_id), "x-role": "admin"},
    )
    assert res.status_code == 201, res.text
    return str(res.json()["data"]["id"])


def _org_unit_scope_headers(org_id: UUID, org_unit_path: str, role: str = "asset_manager") -> dict[str, str]:
    return {
        "x-member-id": str(uuid4()),
        "x-organization-id": str(org_id),
        "x-role": role,
        "x-scope-type": "org_unit",
        "x-org-unit-path": org_unit_path,
    }


async def test_sibling_org_unit_cannot_see_the_asset(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    root_id, root_path = await _make_org_unit(pool, org_id)
    unit_a, path_a = await _make_org_unit(pool, org_id, parent_id=root_id, parent_path=root_path)
    unit_b, _path_b = await _make_org_unit(pool, org_id, parent_id=root_id, parent_path=root_path)
    category_id = await _make_category(pool, org_id)
    asset_id = await _create_asset(client, org_id, unit_a, category_id)
    del path_a, unit_b

    res = await client.get(f"{BASE}/{asset_id}", headers=_org_unit_scope_headers(org_id, "some-other-branch"))
    assert res.status_code == 404
    assert res.json()["code"] == "asset.not_found"


async def test_parent_unit_manager_can_see_the_asset(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    root_id, root_path = await _make_org_unit(pool, org_id)
    unit_a, _path_a = await _make_org_unit(pool, org_id, parent_id=root_id, parent_path=root_path)
    category_id = await _make_category(pool, org_id)
    asset_id = await _create_asset(client, org_id, unit_a, category_id)
    del root_id

    res = await client.get(f"{BASE}/{asset_id}", headers=_org_unit_scope_headers(org_id, root_path))
    assert res.status_code == 200
    assert res.json()["data"]["id"] == asset_id


async def test_self_scope_sees_only_a_held_asset(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    unit_id, _path = await _make_org_unit(pool, org_id)
    category_id = await _make_category(pool, org_id)
    asset_id = await _create_asset(client, org_id, unit_id, category_id)

    member_id = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.members (id, organization_id, idp_subject, email, display_name, status) "
            "VALUES ($1, $2, $3, $4, 'Holder', 'active')",
            member_id,
            org_id,
            f"idp-{member_id.hex[:12]}",
            f"{member_id.hex[:12]}@example.test",
        )
        await conn.execute(
            "UPDATE public.assets SET holder_member_id = $1 WHERE organization_id = $2 AND id = $3",
            member_id,
            org_id,
            UUID(asset_id),
        )

    headers = {
        "x-member-id": str(member_id),
        "x-organization-id": str(org_id),
        "x-role": "member",
        "x-scope-type": "self",
    }
    ok = await client.get(f"{BASE}/{asset_id}", headers=headers)
    assert ok.status_code == 200

    other_headers = {**headers, "x-member-id": str(uuid4())}
    denied = await client.get(f"{BASE}/{asset_id}", headers=other_headers)
    assert denied.status_code == 404


async def test_revoked_grant_stops_at_the_next_request(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    """Headers carry the grant on every request (no session state), so "revoking" it is simply the
    next request not presenting it - proving there is no cached scope decision anywhere."""
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    root_id, root_path = await _make_org_unit(pool, org_id)
    unit_a, _path_a = await _make_org_unit(pool, org_id, parent_id=root_id, parent_path=root_path)
    category_id = await _make_category(pool, org_id)
    asset_id = await _create_asset(client, org_id, unit_a, category_id)

    granted = await client.get(f"{BASE}/{asset_id}", headers=_org_unit_scope_headers(org_id, root_path))
    assert granted.status_code == 200

    revoked = await client.get(f"{BASE}/{asset_id}", headers=_org_unit_scope_headers(org_id, "elsewhere"))
    assert revoked.status_code == 404


# ==============================================================================
# List scope (§B5.3): the id set is a UNION of the scope branches
# ==============================================================================


async def _list_ids(client: httpx.AsyncClient, headers: dict[str, str]) -> list[str]:
    res = await client.get(BASE, headers=headers)
    assert res.status_code == 200, res.text
    return [item["id"] for item in res.json()["data"]["items"]]


async def _make_team(pool: Pool, org_id: UUID) -> UUID:
    team_id = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.teams (id, organization_id, type, code, name) "
            "VALUES ($1, $2, 'team', $3, 'Crew')",
            team_id,
            org_id,
            _token(),
        )
    return team_id


async def _make_member(pool: Pool, org_id: UUID) -> UUID:
    member_id = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.members (id, organization_id, idp_subject, email, display_name, status) "
            "VALUES ($1, $2, $3, $4, 'Holder', 'active')",
            member_id,
            org_id,
            f"idp-{member_id.hex[:12]}",
            f"{member_id.hex[:12]}@example.test",
        )
    return member_id


async def _set_holder(pool: Pool, org_id: UUID, asset_id: str, column: str, holder_id: UUID) -> None:
    assert column in ("holder_member_id", "holder_team_id")
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            f"UPDATE public.assets SET {column} = $1 WHERE organization_id = $2 AND id = $3",  # noqa: S608
            holder_id,
            org_id,
            UUID(asset_id),
        )


async def test_list_sibling_org_units_see_only_their_own_assets(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    root_id, root_path = await _make_org_unit(pool, org_id)
    unit_a, path_a = await _make_org_unit(pool, org_id, parent_id=root_id, parent_path=root_path)
    unit_b, path_b = await _make_org_unit(pool, org_id, parent_id=root_id, parent_path=root_path)
    category_id = await _make_category(pool, org_id)
    asset_a = await _create_asset(client, org_id, unit_a, category_id)
    asset_b = await _create_asset(client, org_id, unit_b, category_id)

    assert await _list_ids(client, _org_unit_scope_headers(org_id, path_a)) == [asset_a]
    assert await _list_ids(client, _org_unit_scope_headers(org_id, path_b)) == [asset_b]


async def test_list_parent_unit_manager_sees_children(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    root_id, root_path = await _make_org_unit(pool, org_id)
    unit_a, _path_a = await _make_org_unit(pool, org_id, parent_id=root_id, parent_path=root_path)
    unit_b, _path_b = await _make_org_unit(pool, org_id, parent_id=root_id, parent_path=root_path)
    category_id = await _make_category(pool, org_id)
    asset_a = await _create_asset(client, org_id, unit_a, category_id)
    asset_b = await _create_asset(client, org_id, unit_b, category_id)

    ids = await _list_ids(client, _org_unit_scope_headers(org_id, root_path))
    assert sorted(ids) == sorted([asset_a, asset_b])


async def test_list_team_holder_is_visible_to_team_members(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    unit_id, _path = await _make_org_unit(pool, org_id)
    category_id = await _make_category(pool, org_id)
    team_id = await _make_team(pool, org_id)
    held = await _create_asset(client, org_id, unit_id, category_id)
    await _create_asset(client, org_id, unit_id, category_id)  # not held by the team
    await _set_holder(pool, org_id, held, "holder_team_id", team_id)

    team_headers = {
        "x-member-id": str(uuid4()),
        "x-organization-id": str(org_id),
        "x-role": "member",
        "x-scope-type": "team",
        "x-scope-id": str(team_id),
        "x-team-ids": str(team_id),
    }
    assert await _list_ids(client, team_headers) == [held]
    outsider = {**team_headers, "x-scope-id": str(uuid4()), "x-team-ids": str(uuid4())}
    assert await _list_ids(client, outsider) == []


async def test_list_self_scope_sees_only_held_assets(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    unit_id, _path = await _make_org_unit(pool, org_id)
    category_id = await _make_category(pool, org_id)
    member_id = await _make_member(pool, org_id)
    held = await _create_asset(client, org_id, unit_id, category_id)
    await _create_asset(client, org_id, unit_id, category_id)
    await _set_holder(pool, org_id, held, "holder_member_id", member_id)

    headers = {
        "x-member-id": str(member_id),
        "x-organization-id": str(org_id),
        "x-role": "member",
        "x-scope-type": "self",
    }
    assert await _list_ids(client, headers) == [held]
    assert await _list_ids(client, {**headers, "x-member-id": str(uuid4())}) == []


async def test_asset_matching_two_scope_branches_appears_once(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    """Under the unit's path *and* held by the caller's team: two UNION branches, one row (§B5.3)."""
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    root_id, root_path = await _make_org_unit(pool, org_id)
    unit_a, _path_a = await _make_org_unit(pool, org_id, parent_id=root_id, parent_path=root_path)
    category_id = await _make_category(pool, org_id)
    team_id = await _make_team(pool, org_id)
    asset_id = await _create_asset(client, org_id, unit_a, category_id)
    await _set_holder(pool, org_id, asset_id, "holder_team_id", team_id)

    headers = {**_org_unit_scope_headers(org_id, root_path), "x-team-ids": str(team_id)}
    res = await client.get(BASE, params={"include_total": "true"}, headers=headers)
    assert res.status_code == 200
    data = res.json()["data"]
    assert [item["id"] for item in data["items"]] == [asset_id]
    assert data["total"] == 1


async def test_list_revoked_grant_stops_at_the_next_request(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    root_id, root_path = await _make_org_unit(pool, org_id)
    unit_a, _path_a = await _make_org_unit(pool, org_id, parent_id=root_id, parent_path=root_path)
    category_id = await _make_category(pool, org_id)
    asset_id = await _create_asset(client, org_id, unit_a, category_id)

    assert await _list_ids(client, _org_unit_scope_headers(org_id, root_path)) == [asset_id]
    assert await _list_ids(client, _org_unit_scope_headers(org_id, "elsewhere")) == []


async def test_other_organizations_assets_never_appear_in_a_list(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_a, org_b = await _create_org(pool), await _create_org(pool)
    unit_a, _ = await _make_org_unit(pool, org_a)
    category_a = await _make_category(pool, org_a)
    await _create_asset(client, org_a, unit_a, category_a)

    admin_b = {"x-member-id": str(uuid4()), "x-organization-id": str(org_b), "x-role": "admin"}
    assert await _list_ids(client, admin_b) == []


async def test_detail_of_another_organizations_asset_is_404(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_a, org_b = await _create_org(pool), await _create_org(pool)
    unit_a, _ = await _make_org_unit(pool, org_a)
    category_a = await _make_category(pool, org_a)
    asset_id = await _create_asset(client, org_a, unit_a, category_a)

    admin_b = {"x-member-id": str(uuid4()), "x-organization-id": str(org_b), "x-role": "admin"}
    res = await client.get(f"{BASE}/{asset_id}", headers=admin_b)
    assert res.status_code == 404
    assert res.json()["code"] == "asset.not_found"


async def test_detail_shows_former_member_marker_and_no_email(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    unit_id, _path = await _make_org_unit(pool, org_id)
    category_id = await _make_category(pool, org_id)
    asset_id = await _create_asset(client, org_id, unit_id, category_id)
    member_id = await _make_member(pool, org_id)
    await _set_holder(pool, org_id, asset_id, "holder_member_id", member_id)
    admin = {"x-member-id": str(uuid4()), "x-organization-id": str(org_id), "x-role": "admin"}

    active = await client.get(f"{BASE}/{asset_id}", headers=admin)
    assert active.json()["data"]["holder"]["display_name"] == "Holder"
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "UPDATE public.members SET status = 'left' WHERE organization_id = $1 AND id = $2",
            org_id,
            member_id,
        )
    gone = await client.get(f"{BASE}/{asset_id}", headers=admin)
    assert gone.json()["data"]["holder"]["display_name"] == "Former member"
    assert "@example.test" not in gone.text
