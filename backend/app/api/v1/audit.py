# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Audit API: list and filter audit events within caller scope (§B5.3, §1590, M1.4-T8)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, Request

from app.api.deps import permission_extra
from app.core.db import tenant_transaction
from app.core.envelope import success_response
from app.core.permissions import ScopeFilter, ScopeType
from app.core.problems import NotFoundError, UnauthorizedError, ValidationFailedError
from app.core.scope import MemberContext, RoleGrant, default_scope_resolver
from app.modules.audit.service import list_audit_events

router = APIRouter(prefix="/audit", tags=["audit"])


def _resolve_caller(request: Request) -> tuple[UUID, ScopeFilter]:
    is_admin = getattr(request.state, "is_platform_admin", False)
    if is_admin or request.headers.get("x-platform-admin") == "true":
        org = request.query_params.get("organization_id")
        if not org:
            raise ValidationFailedError("Platform administrator must specify organization_id")
        try:
            return UUID(org), ScopeFilter.all_organization()
        except ValueError as err:
            raise ValidationFailedError("Invalid organization_id UUID") from err

    member: MemberContext | None = getattr(request.state, "member", None)
    if member is None:
        mid, oid = request.headers.get("x-member-id"), request.headers.get("x-organization-id")
        if mid and oid:
            role = request.headers.get("x-role", "admin")
            st_raw = request.headers.get("x-scope-type", "organization")
            st = ScopeType(st_raw) if st_raw in ScopeType else ScopeType.ORGANIZATION
            grants = (RoleGrant(id="g", organization_id=oid, role_key=role, scope_type=st),)
            member = MemberContext(member_id=mid, organization_id=oid, grants=grants)
    if member is None:
        raise UnauthorizedError()
    try:
        org_uuid = UUID(member.organization_id)
    except ValueError as err:
        raise UnauthorizedError("Invalid organization context") from err

    if not default_scope_resolver.has_permission(member, "audit.read"):
        raise NotFoundError("Resource not found")
    scope_filter = default_scope_resolver.resolve_scope_filter(member, "audit.read")
    if scope_filter.is_empty:
        raise NotFoundError("Resource not found")
    return org_uuid, scope_filter


@router.get("", summary="List audit events", openapi_extra=permission_extra("audit.read"))
@router.get("/events", summary="List audit events", openapi_extra=permission_extra("audit.read"))
async def get_audit_events(
    request: Request,
    *,
    organization_id: UUID | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    action: str | None = None,
    actor_member_id: UUID | None = None,
    from_time: datetime | None = None,
    to_time: datetime | None = None,
    limit: int = Query(50, ge=1, le=100),
) -> dict[str, Any]:
    del organization_id
    req_id = getattr(request.state, "request_id", "") or ""
    org_id, scope_filter = _resolve_caller(request)
    pool = getattr(request.app.state, "pool", None)
    if pool is None:
        return success_response(data=[], request_id=req_id)
    async with tenant_transaction(pool, org_id) as conn:
        events = await list_audit_events(
            conn,
            organization_id=org_id,
            scope_filter=scope_filter,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor_member_id=actor_member_id,
            from_time=from_time,
            to_time=to_time,
            limit=limit,
        )
    return success_response(data=events, request_id=req_id)
