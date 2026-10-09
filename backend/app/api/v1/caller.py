# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Who is calling, for routes that check permissions themselves (§C5.4)."""

from __future__ import annotations

from fastapi import Request

from app.core.problems import UnauthorizedError
from app.core.scope import MemberContext

__all__ = ["request_id", "resolve_member"]


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
