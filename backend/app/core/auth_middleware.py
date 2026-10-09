# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Authenticates each request and provisions its member context (§B5.2, §B5.5, M1.4-T3).

Runs before route handlers. With no ``Authorization`` header the request stays anonymous
(``request.state.member`` is left unset) at no database cost, for public routes such as
``/healthz``. With a bearer token:

1. The active `AuthProvider` verifies it (`UnauthorizedError` for any token it rejects).
2. The AssetFlow organization is looked up only through `platform.resolve_organization` (never a
   direct table read), keyed by the IdP organization claim
   (``urn:zitadel:iam:user:resourceowner:id`` for Zitadel), never an ``org:id`` scope. An unknown
   or archived organization answers exactly like an unrecognized token (no enumeration).
3. The member is found, linked or provisioned by the organization's policy
   (`app.modules.organization.provisioning`).

The result (`MemberContext`, fail-closed on suspension) is rebuilt from the database on every
request; nothing about it is cached. A suspended organization is *not* treated as unknown for an
*existing* member: the request proceeds with `MemberContext.is_suspended = True`, so every
downstream permission check (`ScopeResolver`, already fail-closed on suspension) denies it
uniformly. A principal with no existing member is refused outright while the organization is
suspended (no invite is linked, no member is created): provisioning must never grant new standing
access that would resume, unreviewed, the moment the organization is reactivated.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.db import platform_transaction, tenant_transaction
from app.core.problems import ProblemError, UnauthorizedError, problem_error_handler
from app.core.scope import MemberContext

AUTHORIZATION_HEADER = b"authorization"
_BEARER_PREFIX = "bearer "

# (connection, organization id, verified principal, allow_provisioning) -> member. The API layer
# supplies it (it owns the provisioning import) and raises `UnauthorizedError` for a denied member.
MemberResolver = Callable[..., Awaitable[MemberContext]]


def _extract_bearer(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name.lower() == AUTHORIZATION_HEADER:
            raw: str = value.decode("latin-1")
            if raw.lower().startswith(_BEARER_PREFIX):
                return raw[len(_BEARER_PREFIX) :].strip()
            return None
    return None


async def _authenticate(scope: Scope, token: str, resolver: MemberResolver | None) -> MemberContext:
    if resolver is None:
        raise UnauthorizedError()  # no way to resolve a member: fail closed
    app: Any = scope["app"]
    registry = app.state.registry
    pool = app.state.pool
    principal = await registry.auth.verify_token(token)

    async with platform_transaction(pool) as conn:
        row = await conn.fetchrow(
            "SELECT id, status FROM platform.resolve_organization($1)", principal.organization_id
        )
    if row is None or row["status"] not in ("active", "suspended"):
        raise UnauthorizedError()
    organization_id: UUID = row["id"]
    is_org_suspended = row["status"] == "suspended"

    async with tenant_transaction(pool, organization_id) as conn:
        member = await resolver(conn, organization_id, principal, allow_provisioning=not is_org_suspended)

    if is_org_suspended and not member.is_suspended:
        member = MemberContext(
            member_id=member.member_id,
            organization_id=member.organization_id,
            is_suspended=True,
            grants=member.grants,
            team_ids=member.team_ids,
            primary_org_unit_path=member.primary_org_unit_path,
        )
    scope.setdefault("state", {})["principal"] = principal
    return member


class AuthMiddleware:
    """Pure ASGI middleware: see module docstring."""

    def __init__(self, app: ASGIApp, resolver: MemberResolver | None = None) -> None:
        self.app = app
        self.resolver = resolver

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = _extract_bearer(scope)
        if token is not None:
            try:
                member = await _authenticate(scope, token, self.resolver)
            except ProblemError as exc:
                # Raised here, outside the router: FastAPI's registered handlers only see
                # exceptions from inside ExceptionMiddleware, so this middleware renders its own.
                request = Request(scope, receive=receive)
                response = await problem_error_handler(request, exc)
                await response(scope, receive, send)
                return
            scope.setdefault("state", {})["member"] = member
        await self.app(scope, receive, send)
