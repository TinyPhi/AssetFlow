# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Who is calling, for routes that check permissions themselves (§C5.4)."""

from __future__ import annotations

from fastapi import Request

from app.core.permissions import ScopeType
from app.core.problems import UnauthorizedError
from app.core.scope import MemberContext, RoleGrant

__all__ = ["request_id", "resolve_member"]


def resolve_member(request: Request, default_role: str = "admin") -> MemberContext:
    """Prefer `AuthMiddleware`'s `request.state.member`; a header shortcut remains for tests
    that do not run a full sign-in (mirrors `app.api.v1.org_settings._resolve_member`)."""
    member: MemberContext | None = getattr(request.state, "member", None)
    if member is None:
        mid, oid = request.headers.get("x-member-id"), request.headers.get("x-organization-id")
        if mid and oid:
            role = request.headers.get("x-role", default_role)
            grants = (
                RoleGrant(id="g", organization_id=oid, role_key=role, scope_type=ScopeType.ORGANIZATION),
            )
            member = MemberContext(member_id=mid, organization_id=oid, grants=grants)
    if member is None:
        raise UnauthorizedError()
    return member


def request_id(request: Request) -> str:
    """The request id the middleware stamped, or an empty string."""
    value = getattr(request.state, "request_id", "")
    return value if isinstance(value, str) else ""
