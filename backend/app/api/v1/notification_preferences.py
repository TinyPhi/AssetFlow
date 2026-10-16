# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""A member's own notification preferences: `GET` and `PUT /me/notification-preferences` (M1.5-T7).

Self only: the caller's own member id is the only one the service ever sees, so there is no way to
read or change anyone else's preferences. A caller without the permission gets 404 on the read and
403 on the change (§C4.5, §C5.4 rule 5).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request

from app.api.deps import permission_extra
from app.api.v1.caller import request_id, resolve_member
from app.core.db import tenant_transaction
from app.core.envelope import success_response
from app.core.problems import NotFoundError, PermissionDeniedError, UnauthorizedError
from app.core.scope import default_scope_resolver
from app.modules.notifications import preferences_service
from app.modules.notifications.preference_schemas import PreferencesUpdate

router = APIRouter(prefix="/me/notification-preferences", tags=["notification-preferences"])

PERMISSION = "notification_preference.manage"


def _own_ids(request: Request, *, read: bool) -> tuple[UUID, UUID]:
    member = resolve_member(request, default_role="member")
    if not default_scope_resolver.has_permission(member, PERMISSION):
        raise NotFoundError() if read else PermissionDeniedError()
    try:
        return UUID(member.organization_id), UUID(member.member_id)
    except ValueError as exc:
        raise UnauthorizedError() from exc


@router.get("", summary="Read my notification preferences", openapi_extra=permission_extra(PERMISSION))
async def get_preferences(request: Request) -> dict[str, Any]:
    organization_id, member_id = _own_ids(request, read=True)
    async with tenant_transaction(request.app.state.pool, organization_id) as conn:
        matrix = await preferences_service.get_matrix(conn, member_id=member_id)
    return success_response(data=matrix.model_dump(mode="json"), request_id=request_id(request))


@router.put("", summary="Change my notification preferences", openapi_extra=permission_extra(PERMISSION))
async def put_preferences(request: Request, body: PreferencesUpdate) -> dict[str, Any]:
    organization_id, member_id = _own_ids(request, read=False)
    async with tenant_transaction(request.app.state.pool, organization_id) as conn:
        matrix = await preferences_service.set_preferences(
            conn,
            organization_id=organization_id,
            member_id=member_id,
            changes=body.changes,
            request_id=request_id(request),
        )
    return success_response(data=matrix.model_dump(mode="json"), request_id=request_id(request))
