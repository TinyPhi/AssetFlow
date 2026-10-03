# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Member provisioning at sign-in, by organization policy (§B5.2, §B5.5, M1.4-T3).

Three policies (``organizations.settings->>'provisioning'``, default ``invite_only``):

* ``require_role``: a principal carrying at least one IdP role is provisioned automatically.
* ``invite_only``: only an existing invited member can sign in; it links on an exact,
  case-insensitive email match with a verified email, and never re-links an already-linked member.
* ``open``: any authenticated principal is provisioned automatically (dev/test; the production
  guard for this is ``platform.allow_open_provisioning``, checked at config load).

An existing member (already linked, found by `idp_subject`) always signs in regardless of policy;
the policy only decides what happens for a principal with no member row yet.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

import asyncpg

from app.core.ids import uuid7
from app.core.permissions import ScopeType
from app.core.scope import MemberContext, RoleGrant
from app.modules.audit.service import record_audit_event
from app.providers.auth.base import Principal

type DbConn = asyncpg.Connection[asyncpg.Record] | asyncpg.pool.PoolConnectionProxy[asyncpg.Record]

ProvisioningPolicy = Literal["require_role", "invite_only", "open"]
PROVISIONING_POLICIES: tuple[ProvisioningPolicy, ...] = ("require_role", "invite_only", "open")
DEFAULT_POLICY: ProvisioningPolicy = "invite_only"
PENDING_INVITE_PREFIX = "pending-invite:"
DEFAULT_OPEN_ROLE = "member"


class ProvisioningDeniedError(Exception):
    """Sign-in is refused for this organization and principal; callers answer generically (401)."""


async def get_provisioning_policy(conn: DbConn, organization_id: UUID) -> ProvisioningPolicy:
    raw = await conn.fetchval(
        "SELECT settings->>'provisioning' FROM public.organizations WHERE id = $1", organization_id
    )
    return raw if raw in PROVISIONING_POLICIES else DEFAULT_POLICY


async def resolve_member_context(
    conn: DbConn, organization_id: UUID, principal: Principal, *, allow_provisioning: bool = True
) -> MemberContext:
    """Find, link or create the member for `principal` and load its current role grants.

    `allow_provisioning=False` (a suspended organization) only looks an existing member up by
    `idp_subject`: it never links a pending invite or creates a member, so no new standing access
    is written while the organization is suspended, ready to resume unreviewed the moment it is
    reactivated. Raises `ProvisioningDeniedError` when sign-in must be refused.
    """
    if principal.is_machine:
        raise ProvisioningDeniedError("machine principals are not organization members")

    member = await conn.fetchrow(
        "SELECT id, status FROM public.members WHERE organization_id = $1 AND idp_subject = $2",
        organization_id,
        principal.subject,
    )
    if member is None and allow_provisioning:
        member = await _link_pending_invite(conn, organization_id, principal)
    if member is None and allow_provisioning:
        policy = await get_provisioning_policy(conn, organization_id)
        member = await _provision_new_member(conn, organization_id, principal, policy)
    if member is None:
        raise ProvisioningDeniedError("no existing member found while the organization is suspended")

    grants = await _load_grants(conn, organization_id, member["id"])
    return MemberContext(
        member_id=str(member["id"]),
        organization_id=str(organization_id),
        is_suspended=member["status"] == "suspended",
        grants=grants,
    )


async def _link_pending_invite(
    conn: DbConn, organization_id: UUID, principal: Principal
) -> asyncpg.Record | None:
    if not principal.email or not principal.email_verified:
        return None
    row = await conn.fetchrow(
        "SELECT id, status FROM public.members WHERE organization_id = $1 AND status = 'invited'"
        " AND idp_subject LIKE $2 AND lower(email) = lower($3)",
        organization_id,
        f"{PENDING_INVITE_PREFIX}%",
        principal.email,
    )
    if row is None:
        return None
    member_id = row["id"]
    await conn.execute(
        "UPDATE public.members SET idp_subject = $1, status = 'active'"
        " WHERE organization_id = $2 AND id = $3",
        principal.subject,
        organization_id,
        member_id,
    )
    await record_audit_event(
        conn,
        organization_id=organization_id,
        action="member.invite_linked",
        entity_type="member",
        entity_id=member_id,
        after_state={"email": principal.email},
    )
    linked = await conn.fetchrow(
        "SELECT id, status FROM public.members WHERE organization_id = $1 AND id = $2",
        organization_id,
        member_id,
    )
    assert linked is not None  # noqa: S101 - the row was just updated in this same transaction
    return linked


async def _provision_new_member(
    conn: DbConn, organization_id: UUID, principal: Principal, policy: ProvisioningPolicy
) -> asyncpg.Record:
    if policy == "invite_only":
        raise ProvisioningDeniedError("no invited member matches this principal")
    if policy == "require_role" and not principal.roles:
        raise ProvisioningDeniedError("principal carries no IdP role")
    if not principal.email:
        raise ProvisioningDeniedError("principal has no email to provision a member with")

    role_keys = principal.roles or [DEFAULT_OPEN_ROLE]
    member_id = uuid7()
    await conn.execute(
        "INSERT INTO public.members (id, organization_id, idp_subject, email, display_name, status) "
        "VALUES ($1, $2, $3, $4, $5, 'active')",
        member_id,
        organization_id,
        principal.subject,
        principal.email,
        principal.name or principal.email,
    )
    for role_key in role_keys:
        await conn.execute(
            "INSERT INTO public.role_grants (id, organization_id, member_id, role_key, scope_type, source) "
            "VALUES ($1, $2, $3, $4, 'organization', 'idp')",
            uuid7(),
            organization_id,
            member_id,
            role_key,
        )
    await record_audit_event(
        conn,
        organization_id=organization_id,
        action="member.provision",
        entity_type="member",
        entity_id=member_id,
        after_state={"email": principal.email, "policy": policy, "roles": role_keys},
    )
    await conn.execute(
        "INSERT INTO public.outbox (id, organization_id, event_type, aggregate_type, aggregate_id, payload) "
        "VALUES ($1, $2, 'member.provisioned', 'member', $3, '{}'::jsonb)",
        uuid7(),
        organization_id,
        member_id,
    )
    created = await conn.fetchrow(
        "SELECT id, status FROM public.members WHERE organization_id = $1 AND id = $2",
        organization_id,
        member_id,
    )
    assert created is not None  # noqa: S101 - the row was just inserted in this same transaction
    return created


async def _load_grants(conn: DbConn, organization_id: UUID, member_id: UUID) -> tuple[RoleGrant, ...]:
    rows = await conn.fetch(
        "SELECT id, role_key, scope_type, scope_id, source, expires_at FROM public.role_grants "
        "WHERE organization_id = $1 AND member_id = $2",
        organization_id,
        member_id,
    )
    return tuple(
        RoleGrant(
            id=str(r["id"]),
            organization_id=str(organization_id),
            role_key=r["role_key"],
            scope_type=ScopeType(r["scope_type"]),
            scope_id=str(r["scope_id"]) if r["scope_id"] is not None else None,
            source=r["source"],
            expires_at=r["expires_at"],
        )
        for r in rows
    )
