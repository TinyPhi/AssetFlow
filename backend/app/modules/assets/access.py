# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Record-level access checks for the asset module (§C4.5).

Two different refusals, as the master plan defines them: a caller with no grant carrying the
permission at all gets `PermissionDenied` (403 `auth.permission_denied`); a caller who holds it, but
not for this record or target, gets `ScopeDenied` (403 `scope.denied`). Reads of an out-of-scope
record do not use this module: they answer 404 so existence is never revealed.
"""

from __future__ import annotations

from typing import Any

from app.core.problems import PermissionDeniedError, ScopeDeniedError
from app.core.scope import MemberContext, default_scope_resolver

__all__ = ["require_in_scope", "require_permission"]


def require_permission(caller: MemberContext, permission: str) -> None:
    """Refuse a caller who holds `permission` at no scope at all."""
    if not default_scope_resolver.has_permission(caller, permission):
        raise PermissionDeniedError(f"Permission {permission!r} denied.")


def require_in_scope(
    caller: MemberContext, permission: str, resource: dict[str, Any] | None, *, detail: str | None = None
) -> None:
    """Permission first (`auth.permission_denied`), then scope on the record (`scope.denied`)."""
    require_permission(caller, permission)
    if not default_scope_resolver.check_access(caller, permission, resource):
        raise ScopeDeniedError(detail or f"Permission {permission!r} does not cover this record.")
