# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Resolve the active member context of a request from `AuthMiddleware`'s request state."""

from __future__ import annotations

from fastapi import Request

from app.core.problems import UnauthorizedError
from app.core.scope import MemberContext


def resolve_member(request: Request) -> MemberContext:
    """Resolve the active member context from request state; anonymous requests are refused."""
    member: MemberContext | None = getattr(request.state, "member", None)
    if member is None:
        raise UnauthorizedError()
    return member
