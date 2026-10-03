# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Role grants API: grant, revoke and list, scoped to organization, org unit or team (§B5.3, M1.4-T5)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, Request, status
from pydantic import BaseModel, ConfigDict

from app.core.db import tenant_transaction
from app.core.envelope import success_response
from app.core.permissions import ScopeType
from app.core.problems import NotFoundError, PermissionDeniedError, UnauthorizedError
from app.core.scope import MemberContext, RoleGrant, default_scope_resolver
from app.modules.organization.grants import grant_role, list_grants, revoke_role

router = APIRouter(prefix="/role-grants", tags=["role-grants"])

MANAGE_PERMISSION = "role_grant.manage"


class RoleGrantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    member_id: UUID
    role_key: str
    scope_type: ScopeType
    scope_id: UUID | None = None


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


@router.post("", status_code=status.HTTP_201_CREATED, summary="Grant a role at a scope")
async def create_role_grant(request: Request, body: RoleGrantCreate) -> dict[str, Any]:
    member = _resolve_member(request)
    if not default_scope_resolver.has_permission(member, MANAGE_PERMISSION):
        raise PermissionDeniedError()
    pool = request.app.state.pool
    org_id = UUID(member.organization_id)
    async with tenant_transaction(pool, org_id) as conn:
        grant_id = await grant_role(
            conn,
            organization_id=org_id,
            granter=member,
            target_member_id=body.member_id,
            role_key=body.role_key,
            scope_type=body.scope_type,
            scope_id=body.scope_id,
            request_id=_request_id(request),
        )
    return success_response(
        data={"id": str(grant_id)}, status_code=status.HTTP_201_CREATED, request_id=_request_id(request)
    )


@router.delete("/{grant_id}", summary="Revoke a role grant")
async def delete_role_grant(request: Request, grant_id: UUID) -> dict[str, Any]:
    member = _resolve_member(request)
    if not default_scope_resolver.has_permission(member, MANAGE_PERMISSION):
        raise PermissionDeniedError()
    pool = request.app.state.pool
    org_id = UUID(member.organization_id)
    async with tenant_transaction(pool, org_id) as conn:
        revoked = await revoke_role(
            conn, organization_id=org_id, granter=member, grant_id=grant_id, request_id=_request_id(request)
        )
    if not revoked:
        raise NotFoundError()
    return success_response(data={"revoked": True}, request_id=_request_id(request))


@router.get("", summary="List a member's role grants")
async def get_role_grants(
    request: Request,
    member_id: UUID = Query(...),  # noqa: B008 - FastAPI's own dependency idiom
) -> dict[str, Any]:
    member = _resolve_member(request)
    if not default_scope_resolver.has_permission(member, MANAGE_PERMISSION):
        raise NotFoundError()
    pool = request.app.state.pool
    org_id = UUID(member.organization_id)
    async with tenant_transaction(pool, org_id) as conn:
        grants = await list_grants(conn, organization_id=org_id, member_id=member_id)
    return success_response(data=grants, request_id=_request_id(request))
