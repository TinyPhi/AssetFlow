# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Scoped role grants: grant, revoke and list, nobody grants more than they hold (§B5.3, M1.4-T5).

There is no separate scope cache to invalidate: `MemberContext.grants` is rebuilt from
`role_grants` on every request (`app.modules.organization.provisioning`), so once a grant or
revoke's transaction commits, the very next request already sees the new state — access granted
or revoked applies immediately, by construction, not by an explicit invalidation step.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg

from app.core.ids import uuid7
from app.core.permissions import ROLE_PERMISSIONS, ScopeType
from app.core.problems import NotFoundError, PermissionDeniedError, ValidationFailedError
from app.core.scope import MemberContext, RoleGrant
from app.modules.audit.service import record_audit_event

type DbConn = asyncpg.Connection[asyncpg.Record] | asyncpg.pool.PoolConnectionProxy[asyncpg.Record]


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except ValueError:
        return False


def _covers_scope(
    grant: RoleGrant, scope_type: ScopeType, scope_id: str | None, org_unit_path: str | None
) -> bool:
    if grant.is_expired:
        return False
    if grant.scope_type == ScopeType.ORGANIZATION:
        return True
    if scope_type == ScopeType.ORG_UNIT and grant.scope_type == ScopeType.ORG_UNIT and grant.org_unit_path:
        return org_unit_path is not None and (
            org_unit_path == grant.org_unit_path or org_unit_path.startswith(f"{grant.org_unit_path}.")
        )
    if scope_type == ScopeType.TEAM and grant.scope_type == ScopeType.TEAM:
        return grant.scope_id == scope_id
    return False


def can_grant(
    granter: MemberContext,
    *,
    role_key: str,
    scope_type: ScopeType,
    scope_id: str | None = None,
    org_unit_path: str | None = None,
) -> bool:
    """A granter may grant a role only at a scope where they themselves hold every permission
    that role carries (§B5.3): for each of the role's permissions, some grant of the granter's
    own must both grant that permission and cover the target scope."""
    if granter.is_suspended:
        return False
    permissions = ROLE_PERMISSIONS.get(role_key)
    if not permissions:
        return False
    for permission in permissions:
        matching = [g for g in granter.grants if g.grants_permission(permission)]
        if not any(_covers_scope(g, scope_type, scope_id, org_unit_path) for g in matching):
            return False
    return True


async def _resolve_org_unit_path(conn: DbConn, organization_id: UUID, org_unit_id: UUID) -> str:
    path = await conn.fetchval(
        "SELECT path FROM public.org_units WHERE organization_id = $1 AND id = $2",
        organization_id,
        org_unit_id,
    )
    if path is None:
        raise NotFoundError()
    return str(path)


async def _check_scope_target(
    conn: DbConn, organization_id: UUID, scope_type: ScopeType, scope_id: UUID | None
) -> str | None:
    """Validate `scope_id` against `scope_type` and return the org unit path, if any."""
    if scope_type == ScopeType.ORGANIZATION:
        if scope_id is not None:
            raise ValidationFailedError("scope_id must be empty for organization scope")
        return None
    if scope_id is None:
        raise ValidationFailedError(f"scope_id is required for {scope_type.value} scope")
    if scope_type == ScopeType.ORG_UNIT:
        return await _resolve_org_unit_path(conn, organization_id, scope_id)
    if scope_type == ScopeType.TEAM:
        exists = await conn.fetchval(
            "SELECT 1 FROM public.teams WHERE organization_id = $1 AND id = $2", organization_id, scope_id
        )
        if not exists:
            raise NotFoundError()
        return None
    raise ValidationFailedError(f"unsupported scope_type {scope_type.value!r} for a role grant")


async def grant_role(
    conn: DbConn,
    *,
    organization_id: UUID,
    granter: MemberContext,
    target_member_id: UUID,
    role_key: str,
    scope_type: ScopeType,
    scope_id: UUID | None = None,
    request_id: str | None = None,
) -> UUID:
    """Grant `role_key` to `target_member_id` at the given scope. Raises `NotFoundError` for an
    unknown target or scope (the target does not exist); `PermissionDeniedError` for a granter who
    cannot grant it: a write, not a read, so ScopeDenied is 403 here, not 404 (master plan §C4.5,
    §C5.4 rule 5 reserves 404 for reads)."""
    target = await conn.fetchval(
        "SELECT 1 FROM public.members WHERE organization_id = $1 AND id = $2",
        organization_id,
        target_member_id,
    )
    if not target:
        raise NotFoundError()

    org_unit_path = await _check_scope_target(conn, organization_id, scope_type, scope_id)
    if not can_grant(
        granter,
        role_key=role_key,
        scope_type=scope_type,
        scope_id=str(scope_id) if scope_id is not None else None,
        org_unit_path=org_unit_path,
    ):
        raise PermissionDeniedError(f"cannot grant {role_key!r} at this scope: you do not hold it yourself")

    grant_id = uuid7()
    granted_by = UUID(granter.member_id) if _is_uuid(granter.member_id) else None
    await conn.execute(
        "INSERT INTO public.role_grants"
        " (id, organization_id, member_id, role_key, scope_type, scope_id, granted_by, source)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, 'manual')",
        grant_id,
        organization_id,
        target_member_id,
        role_key,
        scope_type.value,
        scope_id,
        granted_by,
    )
    after_state: dict[str, Any] = {
        "member_id": str(target_member_id),
        "role_key": role_key,
        "scope_type": scope_type.value,
        "scope_id": str(scope_id) if scope_id is not None else None,
    }
    await record_audit_event(
        conn,
        organization_id=organization_id,
        actor_member_id=granted_by,
        action="role_grant.create",
        entity_type="role_grant",
        entity_id=grant_id,
        request_id=request_id,
        after_state=after_state,
    )
    await conn.execute(
        "INSERT INTO public.outbox (id, organization_id, event_type, aggregate_type, aggregate_id, payload) "
        "VALUES ($1, $2, 'role_grant.created', 'role_grant', $3, '{}'::jsonb)",
        uuid7(),
        organization_id,
        grant_id,
    )
    return grant_id


async def revoke_role(
    conn: DbConn,
    *,
    organization_id: UUID,
    granter: MemberContext,
    grant_id: UUID,
    request_id: str | None = None,
) -> bool:
    """Revoke a grant; `False` when it did not exist (idempotent). Only a granter who could grant
    the same role at the same scope may revoke it; refusal is `PermissionDeniedError` (403), same
    as granting (§C4.5, §C5.4 rule 5: 404 is reserved for reads)."""
    row = await conn.fetchrow(
        "SELECT member_id, role_key, scope_type, scope_id FROM public.role_grants"
        " WHERE organization_id = $1 AND id = $2",
        organization_id,
        grant_id,
    )
    if row is None:
        return False

    scope_type = ScopeType(row["scope_type"])
    org_unit_path = None
    if scope_type == ScopeType.ORG_UNIT and row["scope_id"] is not None:
        path = await conn.fetchval(
            "SELECT path FROM public.org_units WHERE organization_id = $1 AND id = $2",
            organization_id,
            row["scope_id"],
        )
        org_unit_path = str(path) if path is not None else None

    if not can_grant(
        granter,
        role_key=row["role_key"],
        scope_type=scope_type,
        scope_id=str(row["scope_id"]) if row["scope_id"] is not None else None,
        org_unit_path=org_unit_path,
    ):
        raise PermissionDeniedError(
            f"cannot revoke {row['role_key']!r} at this scope: you do not hold it yourself"
        )

    await conn.execute(
        "DELETE FROM public.role_grants WHERE organization_id = $1 AND id = $2", organization_id, grant_id
    )
    granted_by = UUID(granter.member_id) if _is_uuid(granter.member_id) else None
    before_state: dict[str, Any] = {
        "member_id": str(row["member_id"]),
        "role_key": row["role_key"],
        "scope_type": row["scope_type"],
        "scope_id": str(row["scope_id"]) if row["scope_id"] is not None else None,
    }
    await record_audit_event(
        conn,
        organization_id=organization_id,
        actor_member_id=granted_by,
        action="role_grant.revoke",
        entity_type="role_grant",
        entity_id=grant_id,
        request_id=request_id,
        before_state=before_state,
    )
    await conn.execute(
        "INSERT INTO public.outbox (id, organization_id, event_type, aggregate_type, aggregate_id, payload) "
        "VALUES ($1, $2, 'role_grant.revoked', 'role_grant', $3, '{}'::jsonb)",
        uuid7(),
        organization_id,
        grant_id,
    )
    return True


async def list_grants(conn: DbConn, *, organization_id: UUID, member_id: UUID) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        "SELECT id, role_key, scope_type, scope_id, granted_by, source, expires_at, created_at"
        " FROM public.role_grants WHERE organization_id = $1 AND member_id = $2 ORDER BY created_at",
        organization_id,
        member_id,
    )
    return [
        {
            "id": str(r["id"]),
            "role_key": r["role_key"],
            "scope_type": r["scope_type"],
            "scope_id": str(r["scope_id"]) if r["scope_id"] is not None else None,
            "granted_by": str(r["granted_by"]) if r["granted_by"] is not None else None,
            "source": r["source"],
            "expires_at": r["expires_at"].isoformat() if r["expires_at"] is not None else None,
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]
