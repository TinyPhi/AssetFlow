# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Resolve the active member context of a request (state first, test-header fallback)."""

from __future__ import annotations

from fastapi import Request

from app.core.permissions import ScopeType
from app.core.problems import UnauthorizedError
from app.core.scope import MemberContext, RoleGrant


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
