# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Adapter that gives `AuthMiddleware` its member resolver (keeps `core` free of module imports)."""

from __future__ import annotations

from uuid import UUID

from app.core.problems import UnauthorizedError
from app.core.scope import MemberContext
from app.modules.organization.provisioning import DbConn, ProvisioningDeniedError, resolve_member_context
from app.providers.auth.base import Principal


async def resolve_member(
    conn: DbConn, organization_id: UUID, principal: Principal, *, allow_provisioning: bool
) -> MemberContext:
    """Resolve (or provision) the member of a verified principal; a denied member is a 401."""
    try:
        return await resolve_member_context(
            conn, organization_id, principal, allow_provisioning=allow_provisioning
        )
    except ProvisioningDeniedError as exc:
        raise UnauthorizedError() from exc
