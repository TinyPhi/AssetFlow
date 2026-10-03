# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Sign-in provisioning end to end: each policy, unknown org, suspended org and member (M1.4-T3).

Exercises the real app factory, `AuthMiddleware` and `/api/v1/audit/events` (already reads
`request.state.member`) over httpx's ASGI transport, against a real PostgreSQL database. The
`mock` auth provider stands in for the IdP: a token is a JSON claims object.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from pg_harness import IsolationDb, PoolFactory

from app.core.db import Pool, tenant_transaction
from app.main import create_app
from app.providers.auth.mock import MockAuthProvider
from app.providers.context import ProviderContext


@dataclass
class _Registry:
    auth: MockAuthProvider


async def _make_client(pool: Pool) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()
    app.state.registry = _Registry(auth=MockAuthProvider(ProviderContext("test", "auth", Path())))
    app.state.pool = pool
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def client(make_pool: PoolFactory) -> AsyncIterator[httpx.AsyncClient]:
    pool = await make_pool("api")
    async for c in _make_client(pool):
        yield c


def _token(**claims: object) -> str:
    return json.dumps(claims)


async def _create_org(
    pool: Pool, *, provisioning: str | None = None, status: str = "active"
) -> tuple[UUID, str]:
    org_id, idp_org = uuid4(), f"idp-{uuid4().hex[:12]}"
    settings = {"provisioning": provisioning} if provisioning else {}
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.organizations"
            " (id, slug, name, idp_organization_id, domain_key, settings, status)"
            " VALUES ($1, $2, 'E2E Org', $3, 'generic', $4::jsonb, $5)",
            org_id,
            f"e2e-{org_id.hex[:12]}",
            idp_org,
            json.dumps(settings),
            status,
        )
    return org_id, idp_org


async def _invite_member(pool: Pool, org_id: UUID, email: str, role_key: str = "admin") -> None:
    member_id = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.members (id, organization_id, idp_subject, email, display_name, status)"
            " VALUES ($1, $2, $3, $4, $4, 'invited')",
            member_id,
            org_id,
            f"pending-invite:{email}",
            email,
        )
        await conn.execute(
            "INSERT INTO public.role_grants (id, organization_id, member_id, role_key, scope_type, source)"
            " VALUES ($1, $2, $3, $4, 'organization', 'manual')",
            uuid4(),
            org_id,
            member_id,
            role_key,
        )


async def _get_events(client: httpx.AsyncClient, token: str) -> httpx.Response:
    return await client.get("/api/v1/audit/events", headers={"Authorization": f"Bearer {token}"})


async def test_unknown_organization_is_rejected_like_an_unknown_token(client: httpx.AsyncClient) -> None:
    res = await _get_events(client, _token(sub="someone", organization_id=f"idp-{uuid4().hex}"))
    assert res.status_code == 401
    assert res.json()["code"] == "auth.unauthorized"


async def test_require_role_provisions_a_principal_carrying_a_role(
    client: httpx.AsyncClient, isolation_db: IsolationDb, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    _, idp_org = await _create_org(pool, provisioning="require_role")
    res = await _get_events(
        client, _token(sub=f"sub-{uuid4().hex}", organization_id=idp_org, roles=["admin"], email="a@e2e.test")
    )
    assert res.status_code == 200


async def test_require_role_rejects_a_principal_with_no_role(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    _, idp_org = await _create_org(pool, provisioning="require_role")
    res = await _get_events(
        client, _token(sub=f"sub-{uuid4().hex}", organization_id=idp_org, email="a@e2e.test")
    )
    assert res.status_code == 401


async def test_invite_only_links_an_invited_member_on_exact_verified_email(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id, idp_org = await _create_org(pool, provisioning="invite_only")
    await _invite_member(pool, org_id, "invitee@e2e.test")
    res = await _get_events(
        client,
        _token(
            sub=f"sub-{uuid4().hex}", organization_id=idp_org, email="invitee@e2e.test", email_verified=True
        ),
    )
    assert res.status_code == 200


async def test_invite_only_rejects_an_unverified_email(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id, idp_org = await _create_org(pool, provisioning="invite_only")
    await _invite_member(pool, org_id, "invitee2@e2e.test")
    res = await _get_events(
        client,
        _token(
            sub=f"sub-{uuid4().hex}", organization_id=idp_org, email="invitee2@e2e.test", email_verified=False
        ),
    )
    assert res.status_code == 401


async def test_invite_only_rejects_a_principal_with_no_invite(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    _, idp_org = await _create_org(pool, provisioning="invite_only")
    res = await _get_events(
        client,
        _token(
            sub=f"sub-{uuid4().hex}", organization_id=idp_org, email="nobody@e2e.test", email_verified=True
        ),
    )
    assert res.status_code == 401


async def test_open_policy_provisions_any_principal_exactly_once(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id, idp_org = await _create_org(pool, provisioning="open")
    subject = f"sub-{uuid4().hex}"
    claims = {"sub": subject, "organization_id": idp_org, "roles": ["admin"], "email": "open@e2e.test"}
    first = await _get_events(client, _token(**claims))
    second = await _get_events(client, _token(**claims))
    assert first.status_code == 200
    assert second.status_code == 200
    async with tenant_transaction(pool, org_id) as conn:
        count = await conn.fetchval(
            "SELECT count(*) FROM public.members WHERE organization_id = $1 AND idp_subject = $2",
            org_id,
            subject,
        )
    assert count == 1


async def test_suspended_member_is_denied_every_request(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id, idp_org = await _create_org(pool, provisioning="open")
    subject = f"sub-{uuid4().hex}"
    claims = {"sub": subject, "organization_id": idp_org, "roles": ["admin"], "email": "susp@e2e.test"}
    ok = await _get_events(client, _token(**claims))
    assert ok.status_code == 200

    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "UPDATE public.members SET status = 'suspended' WHERE organization_id = $1 AND idp_subject = $2",
            org_id,
            subject,
        )
    denied = await _get_events(client, _token(**claims))
    assert denied.status_code == 404


async def test_suspended_organization_denies_without_looking_unknown(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool, migrator_pool = await make_pool("api"), await make_pool("migrator")
    org_id, idp_org = await _create_org(pool, provisioning="open")
    subject = f"sub-{uuid4().hex}"
    claims = {"sub": subject, "organization_id": idp_org, "roles": ["admin"], "email": "org-susp@e2e.test"}
    ok = await _get_events(client, _token(**claims))
    assert ok.status_code == 200

    async with tenant_transaction(migrator_pool, org_id) as conn:
        await conn.execute("UPDATE public.organizations SET status = 'suspended' WHERE id = $1", org_id)
    denied = await _get_events(client, _token(**claims))
    assert denied.status_code == 404  # distinct from the 401 an unknown organization gets


async def test_archived_organization_is_rejected_like_an_unknown_token(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool, migrator_pool = await make_pool("api"), await make_pool("migrator")
    org_id, idp_org = await _create_org(pool, provisioning="open")
    async with tenant_transaction(migrator_pool, org_id) as conn:
        await conn.execute("UPDATE public.organizations SET status = 'archived' WHERE id = $1", org_id)
    res = await _get_events(
        client, _token(sub=f"sub-{uuid4().hex}", organization_id=idp_org, roles=["admin"])
    )
    assert res.status_code == 401
