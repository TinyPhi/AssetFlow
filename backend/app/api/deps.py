# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Shared FastAPI dependencies for the HTTP layer."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from typing import Any
from uuid import UUID

from fastapi import Depends, Request

from app.core.db import tenant_transaction
from app.core.openapi_meta import permission_extra, public_extra
from app.core.problems import (
    NotFoundError,
    PermissionDeniedError,
    UnauthorizedError,
)
from app.core.request_member import resolve_member
from app.core.scope import MemberContext, default_scope_resolver
from app.modules.organization.modules import require_module


def get_member(request: Request) -> MemberContext:
    return resolve_member(request)


def require_member(permission: str | None = None) -> Callable[[Request], MemberContext]:
    def _dependency(request: Request) -> MemberContext:
        member = resolve_member(request)
        if permission is not None and not default_scope_resolver.has_permission(member, permission):
            # Reads out of scope or permission denied return NotFoundError or PermissionDeniedError
            if permission.endswith(".read"):
                raise NotFoundError()
            raise PermissionDeniedError()
        return member

    return _dependency


async def get_db(request: Request, member: MemberContext = Depends(get_member)) -> AsyncGenerator[Any, None]:
    pool = getattr(request.app.state, "pool", None)
    if pool is None:
        raise UnauthorizedError()
    async with tenant_transaction(pool, UUID(member.organization_id)) as conn:
        yield conn


def require_principal(request: Request) -> None:
    """App-wide dependency (AF-005): a route is reachable only with a principal unless it is public.

    "Public" is the ``x-assetflow-public`` OpenAPI marker (``public_extra()``). A route with no
    declaration at all is therefore protected, never open; the authz matrix additionally fails any
    route that declares neither a permission nor ``public``.
    """
    route = request.scope.get("route")
    extra: dict[str, Any] = getattr(route, "openapi_extra", None) or {}
    if extra.get("x-assetflow-public"):
        return
    if getattr(request.state, "is_platform_admin", False):
        return  # a platform admin acts without an organization member; only a verified source sets it
    resolve_member(request)


async def require_platform_admin(request: Request) -> None:
    """Allow only platform admins (§B6.1 rule 4, §B11)."""
    del request
    raise UnauthorizedError()


__all__ = [
    "get_db",
    "get_member",
    "permission_extra",
    "public_extra",
    "require_member",
    "require_module",
    "require_platform_admin",
    "require_principal",
    "resolve_member",
]
