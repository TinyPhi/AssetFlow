# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""`GET /api/v1/me`: the caller's own identity, effective permissions and installed modules (M1.6-T1).

Any authenticated member may call it (no permission beyond signing in) and it returns only the
caller's own data. The web client builds its navigation and guards from it; hiding is a convenience
and every API route still checks permission itself (§C4.9).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request

from app.api.v1.caller import request_id, resolve_member
from app.core.db import tenant_transaction
from app.core.envelope import success_response
from app.core.problems import UnauthorizedError
from app.modules.organization.profile import build_me

router = APIRouter(tags=["me"])


@router.get("/me", summary="My identity, permissions and installed modules")
async def get_me(request: Request) -> dict[str, Any]:
    member = resolve_member(request, default_role="member")
    try:
        organization_id = UUID(member.organization_id)
    except ValueError as exc:
        raise UnauthorizedError() from exc
    async with tenant_transaction(request.app.state.pool, organization_id) as conn:
        body = await build_me(conn, member)
    return success_response(data=body, request_id=request_id(request))
