# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""`require_module`: refuses before any handler runs, on a real database (M1.4-T6)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pg_harness import PoolFactory

from app.api.deps import require_module
from app.core.db import Pool, tenant_transaction
from app.core.problems import ModuleNotInstalledError, UnauthorizedError
from app.core.scope import MemberContext
from app.modules.organization.modules import install_module


async def _create_org(pool: Pool) -> UUID:
    org_id = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.organizations"
            " (id, slug, name, idp_organization_id, domain_key, settings)"
            " VALUES ($1, $2, 'Guard Test Org', $3, 'generic', $4::jsonb)",
            org_id,
            f"guard-{org_id.hex[:12]}",
            f"idp-guard-{uuid4().hex[:12]}",
            json.dumps({}),
        )
    return org_id


def _fake_request(pool: Pool, *, organization_id: str | None = None) -> SimpleNamespace:
    member = MemberContext(member_id="m1", organization_id=organization_id) if organization_id else None
    return SimpleNamespace(
        state=SimpleNamespace(member=member), app=SimpleNamespace(state=SimpleNamespace(pool=pool))
    )


async def test_guard_refuses_unauthenticated_requests(make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    with pytest.raises(UnauthorizedError):
        await require_module("assets")(_fake_request(pool))


async def test_guard_answers_not_installed_before_the_module_exists(make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    with pytest.raises(ModuleNotInstalledError):
        await require_module("assets")(_fake_request(pool, organization_id=str(org_id)))


async def test_guard_passes_once_the_module_is_installed(make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    async with tenant_transaction(pool, org_id) as conn:
        await install_module(conn, org_id, "assets")
    await require_module("assets")(_fake_request(pool, organization_id=str(org_id)))  # does not raise


async def test_guard_is_per_module(make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    async with tenant_transaction(pool, org_id) as conn:
        await install_module(conn, org_id, "assets")
    with pytest.raises(ModuleNotInstalledError):
        await require_module("maintenance")(_fake_request(pool, organization_id=str(org_id)))
