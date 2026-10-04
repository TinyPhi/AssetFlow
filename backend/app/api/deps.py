# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Shared FastAPI dependencies for the HTTP layer."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any
from uuid import UUID

from fastapi import Depends, Request

from app.core.db import tenant_transaction
from app.core.permissions import ScopeType
from app.core.problems import (
    ModuleNotInstalledError,
    NotFoundError,
    PermissionDeniedError,
    UnauthorizedError,
)
from app.core.scope import MemberContext, RoleGrant, default_scope_resolver
from app.modules.organization.modules import ModuleKey, is_module_installed


def resolve_member(request: Request) -> MemberContext:
    """Resolve the active member context from request state or test fallback headers."""
    member: MemberContext | None = getattr(request.state, "member", None)
    if member is None:
        mid, oid = request.headers.get("x-member-id"), request.headers.get("x-organization-id")
        if mid and oid:
            role = request.headers.get("x-role", "admin")
            grants = (
                RoleGrant(id="g", organization_id=oid, role_key=role, scope_type=ScopeType.ORGANIZATION),
            )
            member = MemberContext(member_id=mid, organization_id=oid, grants=grants)
    if member is None:
        raise UnauthorizedError()
    return member


def get_member(request: Request) -> MemberContext:
    return resolve_member(request)


def require_member(permission: str | None = None) -> Callable[[Request], MemberContext]:
    def _dependency(request: Request) -> MemberContext:
        member = resolve_member(request)
        if permission is not None:
            if not default_scope_resolver.has_permission(member, permission):
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


async def require_platform_admin(request: Request) -> None:
    """Allow only platform admins (§B6.1 rule 4, §B11)."""
    del request
    raise UnauthorizedError()


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


def permission_extra(permission: str) -> dict[str, Any]:
    """Declare required permission metadata on an OpenAPI route."""
    return {"x-assetflow-permission": permission}


def public_extra() -> dict[str, Any]:
    """Declare public visibility metadata on an OpenAPI route."""
    return {"x-assetflow-public": True}

