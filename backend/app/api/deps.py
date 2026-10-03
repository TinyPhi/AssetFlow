# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Shared FastAPI dependencies for the HTTP layer."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from fastapi import Request

from app.core.db import tenant_transaction
from app.core.problems import ModuleNotInstalledError, UnauthorizedError
from app.core.scope import MemberContext
from app.modules.organization.modules import ModuleKey, is_module_installed


async def require_platform_admin(request: Request) -> None:
    """Allow only platform admins (§B6.1 rule 4, §B11).

    Sessions and platform roles arrive in M1.4. Until then nobody is authenticated, so this
    dependency always refuses with ``auth.unauthorized`` (fail closed). Tests that need the admin
    view override it with ``app.dependency_overrides``.
    """
    del request
    raise UnauthorizedError()


def require_module(module_key: ModuleKey) -> Callable[[Request], Awaitable[None]]:
    """A route dependency that answers `module.not_installed` before the handler runs (M1.4-T6).

    An uninstalled module's routes behave as if they do not exist: this runs before any query the
    handler itself would make, so no partial work happens first.
    """

    async def _guard(request: Request) -> None:
        member: MemberContext | None = getattr(request.state, "member", None)
        if member is None:
            raise UnauthorizedError()
        pool = getattr(request.app.state, "pool", None)
        if pool is None:
            raise ModuleNotInstalledError()
        async with tenant_transaction(pool, UUID(member.organization_id)) as conn:
            installed = await is_module_installed(conn, UUID(member.organization_id), module_key)
        if not installed:
            raise ModuleNotInstalledError()

    return _guard
