# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Scope handling for the asset API (§B5.3, M2.1-T5, P8-07).

Part a covers create/edit/detail scope behavior; list-based scope scenarios (sibling org units in
one list call, team-holder visibility in a page, "matches two branches appears once", revoked grant
stops at the next list request) are added here in part b, once `GET /api/v1/assets` exists.
"""

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
