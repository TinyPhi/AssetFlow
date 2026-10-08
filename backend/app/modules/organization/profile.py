# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The signed-in member's own view of the system: who they are and what they may do (§B5.8, M1.6-T1).

Drives the web client's navigation and guards. It is a convenience for hiding what the member cannot
use; the API still decides every request. Permissions are computed by the same `ScopeResolver` the
API uses, so the client and the server cannot disagree. Only the caller's own data is returned.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg

from app.core.permissions import DEFAULT_PERMISSIONS
from app.core.scope import MemberContext, ScopeResolver, default_scope_resolver
from app.modules.organization.modules import list_installed_modules
from app.modules.organization.settings import get_settings

type DbConn = asyncpg.Connection[asyncpg.Record] | asyncpg.pool.PoolConnectionProxy[asyncpg.Record]

__all__ = ["build_me", "effective_permissions"]

DEFAULT_LOCALE = "en"
DEFAULT_TIMEZONE = "UTC"


def effective_permissions(
    member: MemberContext, resolver: ScopeResolver = default_scope_resolver
) -> list[dict[str, Any]]:
    """Every permission the member holds, each with the distinct scopes it applies at."""
    result: list[dict[str, Any]] = []
    for permission in sorted(DEFAULT_PERMISSIONS):
        grants = resolver.get_effective_grants_for_permission(member, permission)
        if not grants:
            continue
        scopes = sorted({(g.scope_type.value, g.scope_id) for g in grants}, key=lambda s: (s[0], s[1] or ""))
        result.append(
            {"permission": permission, "scopes": [{"scope_type": t, "scope_id": i} for t, i in scopes]}
        )
    return result


async def build_me(conn: DbConn, member: MemberContext) -> dict[str, Any]:
    """The `GET /api/v1/me` body for `member`."""
    organization_id = UUID(member.organization_id)
    own = None
    try:
        own = await conn.fetchrow(
            "SELECT display_name FROM public.members WHERE id = $1", UUID(member.member_id)
        )
    except ValueError:
        own = None
    organization = await conn.fetchrow(
        "SELECT id, name FROM public.organizations WHERE id = $1", organization_id
    )
    settings = await get_settings(conn, organization_id)
    return {
        "member_id": member.member_id,
        "display_name": own["display_name"] if own is not None else "",
        "locale": settings.get("locale", DEFAULT_LOCALE),
        "organization": {
            "id": member.organization_id,
            "name": organization["name"] if organization is not None else "",
            "timezone": settings.get("timezone", DEFAULT_TIMEZONE),
        },
        "is_suspended": member.is_suspended,
        "permissions": effective_permissions(member),
        "installed_modules": await list_installed_modules(conn, organization_id),
    }
