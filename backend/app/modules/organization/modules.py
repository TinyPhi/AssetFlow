# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Module installation from domain templates (§B5.9, §B7.3, M1.4-T6).

Only two modules exist yet (`organization_modules.module_key` is `CHECK`-constrained to them), so
the dependency rule is the two-entry table below rather than a generic engine; a later module adds
its own dependency the same way. Installing or uninstalling is idempotent and writes its audit
event and outbox row in the same transaction; the route guard (`require_module`) answers
`module.not_installed` before any handler runs, so an uninstalled module's routes look like they
do not exist.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal
from uuid import UUID

import asyncpg
from fastapi import Request

from app.core.db import tenant_transaction
from app.core.ids import uuid7
from app.core.problems import ModuleDependencyError, ModuleNotInstalledError
from app.core.request_member import resolve_member
from app.modules.audit.service import record_audit_event

type DbConn = asyncpg.Connection[asyncpg.Record] | asyncpg.pool.PoolConnectionProxy[asyncpg.Record]

ModuleKey = Literal["assets", "maintenance"]
MODULE_KEYS: tuple[ModuleKey, ...] = ("assets", "maintenance")
MODULE_DEPENDENCIES: dict[ModuleKey, tuple[ModuleKey, ...]] = {"maintenance": ("assets",)}


async def is_module_installed(conn: DbConn, organization_id: UUID, module_key: ModuleKey) -> bool:
    status = await conn.fetchval(
        "SELECT status FROM public.organization_modules WHERE organization_id = $1 AND module_key = $2",
        organization_id,
        module_key,
    )
    return bool(status == "installed")


async def list_installed_modules(conn: DbConn, organization_id: UUID) -> list[ModuleKey]:
    """The module keys currently installed for the organization, in a stable order."""
    rows = await conn.fetch(
        "SELECT module_key FROM public.organization_modules "
        "WHERE organization_id = $1 AND status = 'installed' ORDER BY module_key",
        organization_id,
    )
    installed = {row["module_key"] for row in rows}
    return [key for key in MODULE_KEYS if key in installed]


async def install_module(
    conn: DbConn, organization_id: UUID, module_key: ModuleKey, *, installed_by: UUID | None = None
) -> UUID:
    """Install `module_key` for `organization_id`; a second call is a no-op (idempotent)."""
    for dependency in MODULE_DEPENDENCIES.get(module_key, ()):
        if not await is_module_installed(conn, organization_id, dependency):
            raise ModuleDependencyError(f"{module_key!r} needs {dependency!r} installed first")

    existing = await conn.fetchrow(
        "SELECT id, status FROM public.organization_modules WHERE organization_id = $1 AND module_key = $2",
        organization_id,
        module_key,
    )
    if existing is not None and existing["status"] == "installed":
        installed_id: UUID = existing["id"]
        return installed_id

    module_id: UUID
    if existing is not None:
        module_id = existing["id"]
        await conn.execute(
            "UPDATE public.organization_modules"
            " SET status = 'installed', installed_at = now(), installed_by = $1 WHERE id = $2",
            installed_by,
            module_id,
        )
    else:
        module_id = uuid7()
        await conn.execute(
            "INSERT INTO public.organization_modules"
            " (id, organization_id, module_key, template_key, status, installed_by)"
            " VALUES ($1, $2, $3, $3, 'installed', $4)",
            module_id,
            organization_id,
            module_key,
            installed_by,
        )

    await record_audit_event(
        conn,
        organization_id=organization_id,
        action="module.install",
        entity_type="organization_module",
        entity_id=module_id,
        actor_member_id=installed_by,
        after_state={"module_key": module_key},
    )
    await conn.execute(
        "INSERT INTO public.outbox (id, organization_id, event_type, aggregate_type, aggregate_id, payload) "
        "VALUES ($1, $2, 'module.installed', 'organization_module', $3, $4::jsonb)",
        uuid7(),
        organization_id,
        module_id,
        f'{{"module_key": "{module_key}"}}',
    )
    return module_id


async def uninstall_module(
    conn: DbConn, organization_id: UUID, module_key: ModuleKey, *, uninstalled_by: UUID | None = None
) -> bool:
    """Uninstall `module_key`; returns False (idempotent no-op) when it was not installed."""
    dependents = [key for key, deps in MODULE_DEPENDENCIES.items() if module_key in deps]
    for dependent in dependents:
        if await is_module_installed(conn, organization_id, dependent):
            raise ModuleDependencyError(f"{dependent!r} is installed and needs {module_key!r}")

    row = await conn.fetchrow(
        "SELECT id FROM public.organization_modules"
        " WHERE organization_id = $1 AND module_key = $2 AND status = 'installed'",
        organization_id,
        module_key,
    )
    if row is None:
        return False
    module_id = row["id"]
    await conn.execute(
        "UPDATE public.organization_modules SET status = 'uninstalled' WHERE id = $1", module_id
    )
    await record_audit_event(
        conn,
        organization_id=organization_id,
        action="module.uninstall",
        entity_type="organization_module",
        entity_id=module_id,
        actor_member_id=uninstalled_by,
        after_state={"module_key": module_key},
    )
    await conn.execute(
        "INSERT INTO public.outbox (id, organization_id, event_type, aggregate_type, aggregate_id, payload) "
        "VALUES ($1, $2, 'module.uninstalled', 'organization_module', $3, $4::jsonb)",
        uuid7(),
        organization_id,
        module_id,
        f'{{"module_key": "{module_key}"}}',
    )
    return True


def require_module(module_key: ModuleKey) -> Callable[[Request], Awaitable[None]]:
    """A route dependency that answers `module.not_installed` before the handler runs (M1.4-T6)."""

    async def _guard(request: Request) -> None:
        member = resolve_member(request)
        pool = getattr(request.app.state, "pool", None)
        if pool is None:
            raise ModuleNotInstalledError()
        async with tenant_transaction(pool, UUID(member.organization_id)) as conn:
            installed = await is_module_installed(conn, UUID(member.organization_id), module_key)
        if not installed:
            raise ModuleNotInstalledError()

    return _guard
