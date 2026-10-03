# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Role grant management against a real PostgreSQL: grant/revoke, scope, audit (M1.4-T5).

Tenant isolation of the `role_grants` table itself is `test_role_grants_isolation.py` (P5-01);
this file is about `app.modules.organization.grants` (grant_role/revoke_role/list_grants) and the
"nobody grants more than they hold" rule. Each test creates its own organization rather than
reusing `isolation_db.org_a`/`org_b` (shared session-scoped fixtures other isolation tests also
use).
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from pg_harness import PoolFactory

from app.core.db import Pool, tenant_transaction
from app.core.permissions import ScopeType
from app.core.problems import NotFoundError, ValidationFailedError
from app.core.scope import MemberContext, RoleGrant
from app.modules.organization.grants import grant_role, list_grants, revoke_role
from app.modules.organization.provisioning import resolve_member_context
from app.providers.auth.base import Principal


async def _create_org(pool: Pool) -> UUID:
    org_id = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.organizations"
            " (id, slug, name, idp_organization_id, domain_key, settings)"
            " VALUES ($1, $2, 'Grants Test Org', $3, 'generic', '{}'::jsonb)",
            org_id,
            f"grants-{org_id.hex[:12]}",
            f"idp-grants-{uuid4().hex[:12]}",
        )
    return org_id


async def _create_member(pool: Pool, org_id: UUID, *, email: str) -> UUID:
    member_id = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.members (id, organization_id, idp_subject, email, display_name, status)"
            " VALUES ($1, $2, $3, $4, $4, 'active')",
            member_id,
            org_id,
            f"sub-{member_id.hex[:12]}",
            email,
        )
    return member_id


async def _create_org_unit(pool: Pool, org_id: UUID, *, path: str, parent_id: UUID | None = None) -> UUID:
    unit_id = uuid4()
    code = path.rsplit(".", 1)[-1]
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.org_units (id, organization_id, parent_id, path, type, code, name)"
            " VALUES ($1, $2, $3, $4::ltree, 'division', $5, $5)",
            unit_id,
            org_id,
            parent_id,
            path,
            code,
        )
    return unit_id


async def _org_admin(pool: Pool, organization_id: UUID) -> MemberContext:
    """`granted_by` has a real foreign key to `members`, so a granter needs a real row too."""
    admin_id = await _create_member(pool, organization_id, email=f"admin-{uuid4().hex[:8]}@test")
    return MemberContext(
        member_id=str(admin_id),
        organization_id=str(organization_id),
        grants=(
            RoleGrant(
                id="g",
                organization_id=str(organization_id),
                role_key="admin",
                scope_type=ScopeType.ORGANIZATION,
            ),
        ),
    )


async def _org_unit_admin(
    pool: Pool, organization_id: UUID, *, scope_id: UUID, org_unit_path: str
) -> MemberContext:
    admin_id = await _create_member(pool, organization_id, email=f"unit-admin-{uuid4().hex[:8]}@test")
    return MemberContext(
        member_id=str(admin_id),
        organization_id=str(organization_id),
        grants=(
            RoleGrant(
                id="g",
                organization_id=str(organization_id),
                role_key="admin",
                scope_type=ScopeType.ORG_UNIT,
                scope_id=str(scope_id),
                org_unit_path=org_unit_path,
            ),
        ),
    )


async def test_grant_creates_a_row_with_audit_and_outbox(make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    target_id = await _create_member(pool, org_id, email="a@test")
    granter = await _org_admin(pool, org_id)

    async with tenant_transaction(pool, org_id) as conn:
        grant_id = await grant_role(
            conn,
            organization_id=org_id,
            granter=granter,
            target_member_id=target_id,
            role_key="technician",
            scope_type=ScopeType.ORGANIZATION,
        )
        row = await conn.fetchrow(
            "SELECT member_id, role_key, scope_type, granted_by FROM public.role_grants"
            " WHERE organization_id = $1 AND id = $2",
            org_id,
            grant_id,
        )
        assert row is not None
        assert (row["member_id"], row["role_key"], row["scope_type"]) == (
            target_id,
            "technician",
            "organization",
        )
        assert row["granted_by"] == UUID(granter.member_id)

        action = await conn.fetchval(
            "SELECT action FROM public.audit_events"
            " WHERE organization_id = $1 AND entity_type = 'role_grant' AND entity_id = $2",
            org_id,
            grant_id,
        )
        assert action == "role_grant.create"
        event_type = await conn.fetchval(
            "SELECT event_type FROM public.outbox WHERE organization_id = $1 AND aggregate_id = $2",
            org_id,
            grant_id,
        )
        assert event_type == "role_grant.created"


async def test_grant_to_an_unknown_member_is_not_found(make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    granter = await _org_admin(pool, org_id)
    async with tenant_transaction(pool, org_id) as conn:
        with pytest.raises(NotFoundError):
            await grant_role(
                conn,
                organization_id=org_id,
                granter=granter,
                target_member_id=uuid4(),
                role_key="technician",
                scope_type=ScopeType.ORGANIZATION,
            )


async def test_grant_at_an_unknown_org_unit_is_not_found(make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    target_id = await _create_member(pool, org_id, email="a@test")
    granter = await _org_admin(pool, org_id)
    async with tenant_transaction(pool, org_id) as conn:
        with pytest.raises(NotFoundError):
            await grant_role(
                conn,
                organization_id=org_id,
                granter=granter,
                target_member_id=target_id,
                role_key="technician",
                scope_type=ScopeType.ORG_UNIT,
                scope_id=uuid4(),
            )


async def test_grant_requires_scope_id_for_org_unit_and_team(make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    target_id = await _create_member(pool, org_id, email="a@test")
    granter = await _org_admin(pool, org_id)
    async with tenant_transaction(pool, org_id) as conn:
        with pytest.raises(ValidationFailedError):
            await grant_role(
                conn,
                organization_id=org_id,
                granter=granter,
                target_member_id=target_id,
                role_key="technician",
                scope_type=ScopeType.ORG_UNIT,
            )


async def test_a_narrower_granter_cannot_grant_outside_its_own_subtree(make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    root_id = await _create_org_unit(pool, org_id, path="root")
    hq_id = await _create_org_unit(pool, org_id, path="root.hq", parent_id=root_id)
    ops_id = await _create_org_unit(pool, org_id, path="root.ops", parent_id=root_id)
    target_id = await _create_member(pool, org_id, email="a@test")
    hq_admin = await _org_unit_admin(pool, org_id, scope_id=hq_id, org_unit_path="root.hq")

    async with tenant_transaction(pool, org_id) as conn:
        # within its own subtree: allowed
        grant_id = await grant_role(
            conn,
            organization_id=org_id,
            granter=hq_admin,
            target_member_id=target_id,
            role_key="technician",
            scope_type=ScopeType.ORG_UNIT,
            scope_id=hq_id,
        )
        assert grant_id is not None

        # a sibling subtree: refused, 404 not 403
        with pytest.raises(NotFoundError):
            await grant_role(
                conn,
                organization_id=org_id,
                granter=hq_admin,
                target_member_id=target_id,
                role_key="technician",
                scope_type=ScopeType.ORG_UNIT,
                scope_id=ops_id,
            )

        # cannot grant itself a wider (organization) scope either
        with pytest.raises(NotFoundError):
            await grant_role(
                conn,
                organization_id=org_id,
                granter=hq_admin,
                target_member_id=target_id,
                role_key="technician",
                scope_type=ScopeType.ORGANIZATION,
            )


async def test_revoke_requires_the_same_privilege_as_granting(make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    root_id = await _create_org_unit(pool, org_id, path="root")
    hq_id = await _create_org_unit(pool, org_id, path="root.hq", parent_id=root_id)
    ops_id = await _create_org_unit(pool, org_id, path="root.ops", parent_id=root_id)
    target_id = await _create_member(pool, org_id, email="a@test")
    org_admin = await _org_admin(pool, org_id)
    hq_admin = await _org_unit_admin(pool, org_id, scope_id=hq_id, org_unit_path="root.hq")

    async with tenant_transaction(pool, org_id) as conn:
        ops_grant_id = await grant_role(
            conn,
            organization_id=org_id,
            granter=org_admin,
            target_member_id=target_id,
            role_key="technician",
            scope_type=ScopeType.ORG_UNIT,
            scope_id=ops_id,
        )
        # hq_admin cannot revoke a grant scoped to a sibling subtree
        with pytest.raises(NotFoundError):
            await revoke_role(conn, organization_id=org_id, granter=hq_admin, grant_id=ops_grant_id)

        # the org-wide admin can
        assert (
            await revoke_role(conn, organization_id=org_id, granter=org_admin, grant_id=ops_grant_id) is True
        )
        # revoking again is an idempotent no-op, not an error
        assert (
            await revoke_role(conn, organization_id=org_id, granter=org_admin, grant_id=ops_grant_id) is False
        )


async def test_revoked_access_stops_immediately_on_the_next_resolve(make_pool: PoolFactory) -> None:
    """No cache to invalidate: `resolve_member_context` always re-reads `role_grants`."""
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    target_id = await _create_member(pool, org_id, email="a@test")
    org_admin = await _org_admin(pool, org_id)
    principal = Principal(subject=f"sub-{target_id.hex[:12]}", organization_id="idp-irrelevant")

    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "UPDATE public.members SET idp_subject = $1 WHERE organization_id = $2 AND id = $3",
            principal.subject,
            org_id,
            target_id,
        )
        grant_id = await grant_role(
            conn,
            organization_id=org_id,
            granter=org_admin,
            target_member_id=target_id,
            role_key="technician",
            scope_type=ScopeType.ORGANIZATION,
        )
        before = await resolve_member_context(conn, org_id, principal)
        assert any(g.role_key == "technician" for g in before.grants)

        assert await revoke_role(conn, organization_id=org_id, granter=org_admin, grant_id=grant_id) is True
        after = await resolve_member_context(conn, org_id, principal)
        assert not any(g.role_key == "technician" for g in after.grants)


async def test_org_unit_scoped_grant_resolves_to_the_live_path_after_a_move(make_pool: PoolFactory) -> None:
    """`_load_grants` resolves the org unit's current path at read time, not a stored copy."""
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    root_id = await _create_org_unit(pool, org_id, path="root")
    hq_id = await _create_org_unit(pool, org_id, path="root.hq", parent_id=root_id)
    target_id = await _create_member(pool, org_id, email="a@test")
    org_admin = await _org_admin(pool, org_id)
    principal = Principal(subject=f"sub-{target_id.hex[:12]}", organization_id="idp-irrelevant")

    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "UPDATE public.members SET idp_subject = $1 WHERE organization_id = $2 AND id = $3",
            principal.subject,
            org_id,
            target_id,
        )
        await grant_role(
            conn,
            organization_id=org_id,
            granter=org_admin,
            target_member_id=target_id,
            role_key="technician",
            scope_type=ScopeType.ORG_UNIT,
            scope_id=hq_id,
        )
        member = await resolve_member_context(conn, org_id, principal)
        grant = next(g for g in member.grants if g.role_key == "technician")
        assert grant.org_unit_path == "root.hq"

        # rename the unit's path directly (simulating what a future move operation would do)
        await conn.execute(
            "UPDATE public.org_units SET path = 'root.hq_renamed'::ltree"
            " WHERE organization_id = $1 AND id = $2",
            org_id,
            hq_id,
        )
        member_after = await resolve_member_context(conn, org_id, principal)
        grant_after = next(g for g in member_after.grants if g.role_key == "technician")
        assert grant_after.org_unit_path == "root.hq_renamed"


async def test_list_grants_returns_a_members_grants(make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    target_id = await _create_member(pool, org_id, email="a@test")
    granter = await _org_admin(pool, org_id)
    async with tenant_transaction(pool, org_id) as conn:
        await grant_role(
            conn,
            organization_id=org_id,
            granter=granter,
            target_member_id=target_id,
            role_key="technician",
            scope_type=ScopeType.ORGANIZATION,
        )
        grants = await list_grants(conn, organization_id=org_id, member_id=target_id)
    assert len(grants) == 1
    assert grants[0]["role_key"] == "technician"
    assert grants[0]["scope_type"] == "organization"
