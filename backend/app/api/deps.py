# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Shared FastAPI dependencies for the HTTP layer."""

from __future__ import annotations

from fastapi import Request

from app.core.problems import UnauthorizedError


async def require_platform_admin(request: Request) -> None:
    """Allow only platform admins (§B6.1 rule 4, §B11).

    Sessions and platform roles arrive in M1.4. Until then nobody is authenticated, so this
    dependency always refuses with ``auth.unauthorized`` (fail closed). Tests that need the admin
    view override it with ``app.dependency_overrides``.
    """
    del request
    raise UnauthorizedError()
