# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""`GET /api/v1/me` against a real PostgreSQL (M1.6-T1): who I am, what I may do, what is installed.

The permissions come from the same resolver the API uses, so the web client's navigation and the
server agree; only the caller's own data is returned and another organization's is never visible.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx
import pytest
from pg_harness import IsolationDb, PoolFactory

from app.core.db import Pool, tenant_transaction
from app.main import create_app
from app.providers.auth.mock import MockAuthProvider
from app.providers.context import ProviderContext
from app.providers.telemetry.noop import NoOpTelemetryProvider

ME = "/api/v1/me"


class _Registry:
    def __init__(self) -> None:
        self.auth = MockAuthProvider(ProviderContext("test", "auth", Path()))
        self.telemetry = NoOpTelemetryProvider()


@pytest.fixture
async def client(make_pool: PoolFactory) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()
    app.state.registry = _Registry()
    app.state.pool = await make_pool("api")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def admin_db(isolation_db: IsolationDb) -> AsyncIterator[asyncpg.Connection[asyncpg.Record]]:
    conn = await asyncpg.connect(isolation_db.admin_dsn)
    yield conn
    await conn.execute("DELETE FROM public.organization_modules")
    await conn.execute("UPDATE public.organizations SET settings = '{}'::jsonb")
    await conn.close()


async def _member(pool: Pool, org_id: UUID, name: str) -> UUID:
    member_id = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.members (id, organization_id, email, status, idp_subject, display_name) "
            "VALUES ($1, $2, $3, 'active', $4, $5)",
            member_id,
            org_id,
            f"{member_id.hex[:8]}@example.test",
            f"sub-{member_id}",
            name,
        )
    return member_id


def _as(org_id: UUID, member_id: UUID, role: str) -> dict[str, str]:
    return {
        "x-organization-id": str(org_id),
        "x-member-id": str(member_id),
        "x-role": role,
        "x-scope-type": "organization",
    }


def _perms(body: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    return {p["permission"]: p["scopes"] for p in body["permissions"]}


async def test_the_member_sees_their_own_identity_organization_and_settings(
    client: httpx.AsyncClient,
    make_pool: PoolFactory,
    isolation_db: IsolationDb,
    admin_db: asyncpg.Connection[asyncpg.Record],
) -> None:
    org = isolation_db.org_a
    me = await _member(await make_pool("api"), org, "Ada Lovelace")
    await admin_db.execute(
        "UPDATE public.organizations SET settings = $2::jsonb WHERE id = $1",
        org,
        '{"locale": "hi", "timezone": "Asia/Kolkata"}',
    )
    res = await client.get(ME, headers=_as(org, me, "member"))
    assert res.status_code == 200, res.text
    body = res.json()["data"]
    assert body["member_id"] == str(me)
    assert body["display_name"] == "Ada Lovelace"
    assert body["locale"] == "hi"
    assert body["organization"]["id"] == str(org)
    assert body["organization"]["timezone"] == "Asia/Kolkata"
    assert body["organization"]["name"]
    assert body["is_suspended"] is False


async def test_defaults_apply_when_the_organization_has_no_settings(
    client: httpx.AsyncClient,
    make_pool: PoolFactory,
    isolation_db: IsolationDb,
    admin_db: asyncpg.Connection[asyncpg.Record],
) -> None:
    me = await _member(await make_pool("api"), isolation_db.org_a, "Bob")
    body = (await client.get(ME, headers=_as(isolation_db.org_a, me, "member"))).json()["data"]
    assert (body["locale"], body["organization"]["timezone"]) == ("en", "UTC")


async def test_a_plain_member_has_only_the_permissions_of_their_role(
    client: httpx.AsyncClient, make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    me = await _member(await make_pool("api"), isolation_db.org_a, "Cy")
    body = (await client.get(ME, headers=_as(isolation_db.org_a, me, "member"))).json()["data"]
    perms = _perms(body)
    assert "notification.read" in perms
    assert "asset.read" in perms
    assert "role_grant.manage" not in perms
    assert "org_unit.create" not in perms
    assert perms["asset.read"] == [{"scope_type": "organization", "scope_id": None}]


async def test_an_admin_holds_every_organization_permission_at_organization_scope(
    client: httpx.AsyncClient, make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    from app.core.permissions import DEFAULT_PERMISSIONS  # noqa: PLC0415 - only this test needs it

    me = await _member(await make_pool("api"), isolation_db.org_a, "Dee")
    body = (await client.get(ME, headers=_as(isolation_db.org_a, me, "admin"))).json()["data"]
    # `*` never covers the platform operator permissions: they are not an organization admin's.
    assert set(_perms(body)) == {p for p in DEFAULT_PERMISSIONS if not p.startswith("platform.")}
    assert all(
        scopes == [{"scope_type": "organization", "scope_id": None}] for scopes in _perms(body).values()
    )


async def test_the_permissions_are_the_ones_the_api_enforces(
    client: httpx.AsyncClient, make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    """A permission /me lists is one a real route lets the caller use; one it omits is refused."""
    org, api = isolation_db.org_a, await make_pool("api")
    technician = await _member(api, org, "Eve")
    perms = _perms((await client.get(ME, headers=_as(org, technician, "technician"))).json()["data"])
    assert "team.read" in perms and "role_grant.manage" not in perms
    assert (await client.get("/api/v1/teams", headers=_as(org, technician, "technician"))).status_code == 200
    denied = await client.post(
        "/api/v1/teams",
        headers=_as(org, technician, "technician"),
        json={"code": "x", "name": "X", "type": "crew"},
    )
    assert denied.status_code in {403, 404}


async def test_installed_modules_are_listed_and_follow_installation(
    client: httpx.AsyncClient,
    make_pool: PoolFactory,
    isolation_db: IsolationDb,
    admin_db: asyncpg.Connection[asyncpg.Record],
) -> None:
    org = isolation_db.org_a
    me = await _member(await make_pool("api"), org, "Fay")
    headers = _as(org, me, "member")
    assert (await client.get(ME, headers=headers)).json()["data"]["installed_modules"] == []

    await admin_db.execute(
        "INSERT INTO public.organization_modules (id, organization_id, module_key, template_key, status) "
        "VALUES ($1, $2, 'assets', 'test', 'installed')",
        uuid4(),
        org,
    )
    await admin_db.execute(
        "INSERT INTO public.organization_modules (id, organization_id, module_key, template_key, status) "
        "VALUES ($1, $2, 'maintenance', 'test', 'uninstalled')",
        uuid4(),
        org,
    )
    assert (await client.get(ME, headers=headers)).json()["data"]["installed_modules"] == ["assets"]


async def test_another_organizations_modules_and_settings_are_never_visible(
    client: httpx.AsyncClient,
    make_pool: PoolFactory,
    isolation_db: IsolationDb,
    admin_db: asyncpg.Connection[asyncpg.Record],
) -> None:
    await admin_db.execute(
        "INSERT INTO public.organization_modules (id, organization_id, module_key, template_key, status) "
        "VALUES ($1, $2, 'assets', 'test', 'installed')",
        uuid4(),
        isolation_db.org_a,
    )
    await admin_db.execute(
        'UPDATE public.organizations SET settings = \'{"locale": "hi"}\'::jsonb WHERE id = $1',
        isolation_db.org_a,
    )
    in_b = await _member(await make_pool("api"), isolation_db.org_b, "Gus")
    body = (await client.get(ME, headers=_as(isolation_db.org_b, in_b, "admin"))).json()["data"]
    assert body["installed_modules"] == []
    assert body["locale"] == "en"
    assert body["organization"]["id"] == str(isolation_db.org_b)


async def test_the_caller_cannot_ask_for_someone_else(
    client: httpx.AsyncClient, make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    api = await make_pool("api")
    ada = await _member(api, isolation_db.org_a, "Ada")
    bob = await _member(api, isolation_db.org_a, "Bob")
    body = (await client.get(ME, headers=_as(isolation_db.org_a, ada, "member"))).json()["data"]
    assert body["member_id"] == str(ada) and body["display_name"] == "Ada"
    assert str(bob) not in str(body) and "Bob" not in str(body)
    assert (
        await client.get(f"{ME}/{bob}", headers=_as(isolation_db.org_a, ada, "member"))
    ).status_code == 404


async def test_an_unauthenticated_call_is_401(client: httpx.AsyncClient) -> None:
    assert (await client.get(ME)).status_code == 401
