# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Who is calling, for routes that check permissions themselves (§C5.4)."""

from __future__ import annotations

from uuid import UUID

from fastapi import Request

from app.core.permissions import ScopeType
from app.core.problems import UnauthorizedError, ValidationFailedError
from app.core.scope import MemberContext, RoleGrant

__all__ = ["request_id", "resolve_caller", "resolve_member"]


def resolve_member(request: Request, default_role: str = "admin") -> MemberContext:
    """The member `AuthMiddleware` authenticated for this request; anonymous requests are refused."""
    member: MemberContext | None = getattr(request.state, "member", None)
    if member is None:
        raise UnauthorizedError()
    return member


def request_id(request: Request) -> str:
    """The request id the middleware stamped, or an empty string."""
    value = getattr(request.state, "request_id", "")
    return value if isinstance(value, str) else ""


def resolve_caller(request: Request) -> tuple[UUID, MemberContext]:
    """The organization and member for this request; a platform admin must name ``organization_id``."""
    is_admin = getattr(request.state, "is_platform_admin", False)
    if is_admin:
        org = request.query_params.get("organization_id")
        if not org:
            raise ValidationFailedError("Platform administrator must specify organization_id")
        try:
            org_uuid = UUID(org)
            admin_grant = RoleGrant(
                id="platform-admin",
                organization_id=str(org_uuid),
                role_key="admin",
                scope_type=ScopeType.ORGANIZATION,
            )
            admin_member = MemberContext(
                member_id="platform-admin", organization_id=str(org_uuid), grants=(admin_grant,)
            )
            return org_uuid, admin_member
        except ValueError as err:
            raise ValidationFailedError("Invalid organization_id UUID") from err

    member: MemberContext | None = getattr(request.state, "member", None)
    if member is None:
        raise UnauthorizedError()
    try:
        org_uuid = UUID(member.organization_id)
    except ValueError as err:
        raise UnauthorizedError("Invalid organization context") from err
    return org_uuid, member
