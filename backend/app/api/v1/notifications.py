# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The in-app inbox API: list, unread count, mark read, mark all read (§B4.5, §B6.3, M1.5-T3)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, Request

from app.api.deps import permission_extra
from app.core.db import tenant_transaction
from app.core.envelope import success_response
from app.core.permissions import ScopeType
from app.core.problems import NotFoundError, UnauthorizedError
from app.core.scope import MemberContext, RoleGrant, default_scope_resolver
from app.modules.notifications import service

router = APIRouter(prefix="/notifications", tags=["notifications"])

READ_PERMISSION = "notification.read"


def _resolve_member(request: Request) -> MemberContext:
    """Prefer `AuthMiddleware`'s `request.state.member`; a header shortcut remains for tests
    that do not run a full sign-in (mirrors `app.api.v1.org_settings._resolve_member`)."""
    member: MemberContext | None = getattr(request.state, "member", None)
    if member is None:
        mid, oid = request.headers.get("x-member-id"), request.headers.get("x-organization-id")
        if mid and oid:
            role = request.headers.get("x-role", "member")
            grants = (
                RoleGrant(id="g", organization_id=oid, role_key=role, scope_type=ScopeType.ORGANIZATION),
            )
            member = MemberContext(member_id=mid, organization_id=oid, grants=grants)
    if member is None:
        raise UnauthorizedError()
    return member


def _require_read(member: MemberContext) -> None:
    if not default_scope_resolver.has_permission(member, READ_PERMISSION):
        raise NotFoundError()


def _request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", "")
    return value if isinstance(value, str) else ""


@router.get("", summary="List the caller's own inbox", openapi_extra=permission_extra(READ_PERMISSION))
async def list_notifications(
    request: Request,
    *,
    unread_only: bool = False,
    updated_since: datetime | None = None,
    after: str | None = Query(default=None, description="Cursor from a previous page's next_cursor"),
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    member = _resolve_member(request)
    _require_read(member)
    cursor = service.decode_cursor(after) if after else None
    pool = request.app.state.pool
    async with tenant_transaction(pool, UUID(member.organization_id)) as conn:
        rows, next_cursor = await service.list_inbox(
            conn,
            member_id=UUID(member.member_id),
            unread_only=unread_only,
            updated_since=updated_since,
            after=cursor,
            limit=limit,
        )
    data = {"items": [_serialize(row) for row in rows], "next_cursor": next_cursor}
    return success_response(data=data, request_id=_request_id(request))


@router.get("/unread-count", summary="How many of the caller's own notices are unread", openapi_extra=permission_extra(READ_PERMISSION))
async def get_unread_count(request: Request) -> dict[str, Any]:
    member = _resolve_member(request)
    _require_read(member)
    pool = request.app.state.pool
    async with tenant_transaction(pool, UUID(member.organization_id)) as conn:
        count = await service.unread_count(conn, member_id=UUID(member.member_id))
    return success_response(data={"unread": count}, request_id=_request_id(request))


@router.post("/{notification_id}/read", summary="Mark one notice as read", openapi_extra=permission_extra(READ_PERMISSION))
async def mark_read(request: Request, notification_id: UUID) -> dict[str, Any]:
    member = _resolve_member(request)
    _require_read(member)
    req_id = _request_id(request)
    pool = request.app.state.pool
    async with tenant_transaction(pool, UUID(member.organization_id)) as conn:
        changed = await service.mark_read(
            conn,
            organization_id=UUID(member.organization_id),
            caller_member_id=UUID(member.member_id),
            notification_id=notification_id,
            request_id=req_id,
        )
    return success_response(data={"changed": changed}, request_id=req_id)


@router.post("/read-all", summary="Mark every one of the caller's own notices as read", openapi_extra=permission_extra(READ_PERMISSION))
async def mark_all_read(request: Request) -> dict[str, Any]:
    member = _resolve_member(request)
    _require_read(member)
    req_id = _request_id(request)
    pool = request.app.state.pool
    async with tenant_transaction(pool, UUID(member.organization_id)) as conn:
        count = await service.mark_all_read(
            conn,
            organization_id=UUID(member.organization_id),
            caller_member_id=UUID(member.member_id),
            request_id=req_id,
        )
    return success_response(data={"changed": count}, request_id=req_id)


def _serialize(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "event_type": row["event_type"],
        "template_key": row["template_key"],
        "title_key": row["title_key"],
        "body": row["body"],
        "link_entity_type": row["link_entity_type"],
        "link_entity_id": str(row["link_entity_id"]) if row["link_entity_id"] else None,
        "read_at": row["read_at"].isoformat() if row["read_at"] else None,
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }
