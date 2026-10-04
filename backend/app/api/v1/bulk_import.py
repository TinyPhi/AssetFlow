# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Bulk import API: preview (writes nothing) and commit (all or nothing) (§B5.3, M1.4-T7).

Named `bulk_import`, not `import` (the plan's suggested name): `import` is a Python keyword.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request

from app.api.deps import permission_extra
from app.core.db import tenant_transaction
from app.core.envelope import success_response
from app.core.permissions import ScopeType
from app.core.problems import PermissionDeniedError, UnauthorizedError
from app.core.scope import MemberContext, RoleGrant, default_scope_resolver
from app.modules.organization.bulk_import import ImportRequest, run_import

router = APIRouter(prefix="/import", tags=["import"])

MANAGE_PERMISSION = "member.manage"


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


@router.post("/preview", summary="Validate an import; writes nothing", openapi_extra=permission_extra(MANAGE_PERMISSION))
async def preview_import(request: Request, body: ImportRequest) -> dict[str, Any]:
    member = _resolve_member(request)
    if not default_scope_resolver.has_permission(member, MANAGE_PERMISSION):
        raise PermissionDeniedError()
    pool = request.app.state.pool
    org_id = UUID(member.organization_id)
    async with tenant_transaction(pool, org_id) as conn:
        result = await run_import(conn, organization_id=org_id, data=body, dry_run=True)
    return success_response(data=result.as_dict(), request_id=_request_id(request))


@router.post("/commit", summary="Commit an import: all rows, or none", openapi_extra=permission_extra(MANAGE_PERMISSION))
async def commit_import(request: Request, body: ImportRequest) -> dict[str, Any]:
    member = _resolve_member(request)
    if not default_scope_resolver.has_permission(member, MANAGE_PERMISSION):
        raise PermissionDeniedError()
    pool = request.app.state.pool
    org_id = UUID(member.organization_id)
    actor_id = UUID(member.member_id) if _is_uuid(member.member_id) else None
    async with tenant_transaction(pool, org_id) as conn:
        result = await run_import(
            conn,
            organization_id=org_id,
            data=body,
            dry_run=False,
            actor_member_id=actor_id,
            request_id=_request_id(request),
        )
    return success_response(data=result.as_dict(), request_id=_request_id(request))


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except ValueError:
        return False
