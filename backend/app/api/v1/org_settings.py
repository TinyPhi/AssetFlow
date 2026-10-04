# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Organization settings API: read and change, every change audited (§B5.3, M1.4-T9)."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import permission_extra
from app.core.db import tenant_transaction
from app.core.envelope import success_response
from app.core.permissions import ScopeType
from app.core.problems import NotFoundError, PermissionDeniedError, UnauthorizedError
from app.core.scope import MemberContext, RoleGrant, default_scope_resolver
from app.modules.organization.settings import get_settings, update_settings

router = APIRouter(prefix="/organizations/settings", tags=["organization-settings"])

READ_PERMISSION = "organization.settings_read"
MANAGE_PERMISSION = "organization.settings_manage"


class OrganizationSettingsUpdate(BaseModel):
    """A partial update: only the fields given are changed (§B10)."""

    model_config = ConfigDict(extra="forbid")

    provisioning: str | None = None
    locale: str | None = None
    timezone: str | None = None
    currency: str | None = None
    default_calendar_id: UUID | None = None


def _resolve_member(request: Request) -> MemberContext:
    """Prefer `AuthMiddleware`'s `request.state.member`; a header shortcut remains for tests
    that do not run a full sign-in (mirrors `app.api.v1.audit._resolve_caller`)."""
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


def _request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", "")
    return value if isinstance(value, str) else ""


@router.get("", summary="Read organization settings", openapi_extra=permission_extra(READ_PERMISSION))
async def get_organization_settings(request: Request) -> dict[str, Any]:
    member = _resolve_member(request)
    if not default_scope_resolver.has_permission(member, READ_PERMISSION):
        raise NotFoundError()
    pool = request.app.state.pool
    async with tenant_transaction(pool, UUID(member.organization_id)) as conn:
        settings = await get_settings(conn, UUID(member.organization_id))
    return success_response(data=settings, request_id=_request_id(request))


@router.patch("", summary="Change organization settings", openapi_extra=permission_extra(MANAGE_PERMISSION))
async def patch_organization_settings(
    request: Request, body: Annotated[OrganizationSettingsUpdate, Field()]
) -> dict[str, Any]:
    member = _resolve_member(request)
    if not default_scope_resolver.has_permission(member, MANAGE_PERMISSION):
        raise PermissionDeniedError()
    changes = body.model_dump(exclude_unset=True)
    pool = request.app.state.pool
    async with tenant_transaction(pool, UUID(member.organization_id)) as conn:
        settings = await update_settings(
            conn, UUID(member.organization_id), changes, actor_member_id=UUID(member.member_id)
        )
    return success_response(data=settings, request_id=_request_id(request))
