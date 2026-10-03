# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Module installation against a real PostgreSQL: dependency rule, idempotency, audit (M1.4-T6).

Each test creates its own organization rather than reusing `isolation_db.org_a`/`org_b`: those are
shared session-scoped fixtures other isolation tests also use, and `organization_modules` has a
`UNIQUE (organization_id, module_key)` constraint a leftover row would violate.
"""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import asyncpg
import pytest
from pg_harness import PoolFactory

from app.core.db import Pool, tenant_transaction
from app.core.problems import ModuleDependencyError
from app.modules.organization.modules import install_module, is_module_installed, uninstall_module


async def _create_org(pool: Pool) -> UUID:
    org_id = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.organizations"
            " (id, slug, name, idp_organization_id, domain_key, settings)"
            " VALUES ($1, $2, 'Module Test Org', $3, 'generic', $4::jsonb)",
            org_id,
            f"mod-{org_id.hex[:12]}",
            f"idp-mod-{uuid4().hex[:12]}",
            json.dumps({}),
        )
    return org_id


async def test_maintenance_refuses_without_assets_then_installs_in_order(make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    async with tenant_transaction(pool, org_id) as conn:
        with pytest.raises(ModuleDependencyError):
            await install_module(conn, org_id, "maintenance")
        assert await is_module_installed(conn, org_id, "maintenance") is False

        await install_module(conn, org_id, "assets")
        assert await is_module_installed(conn, org_id, "assets") is True

        await install_module(conn, org_id, "maintenance")
        assert await is_module_installed(conn, org_id, "maintenance") is True


async def test_install_is_idempotent(make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    async with tenant_transaction(pool, org_id) as conn:
        first = await install_module(conn, org_id, "assets")
        second = await install_module(conn, org_id, "assets")
        assert first == second
        count = await conn.fetchval(
            "SELECT count(*) FROM public.organization_modules WHERE organization_id = $1", org_id
        )
    assert count == 1


async def test_uninstall_refuses_while_a_dependent_is_installed(make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    async with tenant_transaction(pool, org_id) as conn:
        await install_module(conn, org_id, "assets")
        await install_module(conn, org_id, "maintenance")
        with pytest.raises(ModuleDependencyError):
            await uninstall_module(conn, org_id, "assets")

        assert await uninstall_module(conn, org_id, "maintenance") is True
        assert await uninstall_module(conn, org_id, "assets") is True
        # idempotent: uninstalling an already-uninstalled module is a no-op, not an error
        assert await uninstall_module(conn, org_id, "assets") is False


async def test_install_and_uninstall_write_audit_events_and_outbox_rows(make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    async with tenant_transaction(pool, org_id) as conn:
        module_id = await install_module(conn, org_id, "assets")
        await uninstall_module(conn, org_id, "assets")

        actions = await conn.fetch(
            "SELECT action FROM public.audit_events"
            " WHERE organization_id = $1 AND entity_type = 'organization_module' AND entity_id = $2"
            " ORDER BY created_at",
            org_id,
            module_id,
        )
        assert [r["action"] for r in actions] == ["module.install", "module.uninstall"]

        events = await conn.fetch(
            "SELECT event_type FROM public.outbox"
            " WHERE organization_id = $1 AND aggregate_id = $2 ORDER BY created_at",
            org_id,
            module_id,
        )
        assert [r["event_type"] for r in events] == ["module.installed", "module.uninstalled"]


async def test_module_key_is_fail_closed_at_the_database(make_pool: PoolFactory) -> None:
    """The CHECK constraint is the backstop even if application code ever picked a bad key."""
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    with pytest.raises(asyncpg.CheckViolationError):
        async with tenant_transaction(pool, org_id) as conn:
            await conn.execute(
                "INSERT INTO public.organization_modules"
                " (id, organization_id, module_key, template_key, status)"
                " VALUES (gen_random_uuid(), $1, 'not-a-real-module', 'x', 'installed')",
                org_id,
            )
