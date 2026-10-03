# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Organization creation: first admin, root org unit, audit event and outbox row (§B5.2, §B5.5, M1.4-T2)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import asyncpg

from app.core.db import Pool, platform_transaction, tenant_transaction
from app.core.ids import uuid7
from app.modules.audit.service import record_audit_event

type DbConn = asyncpg.Connection[asyncpg.Record] | asyncpg.pool.PoolConnectionProxy[asyncpg.Record]

ADMIN_ROLE_KEY = "admin"
ROOT_ORG_UNIT_CODE = "root"
ROOT_ORG_UNIT_TYPE = "root"


@dataclass(frozen=True)
class OrganizationCreated:
    organization_id: UUID
    admin_member_id: UUID | None
    created: bool
    """False when the slug already existed: an idempotent no-op, not an error."""


async def find_organization_id_by_slug(conn: DbConn, slug: str) -> UUID | None:
    """Look a slug up before the organization's id is known (platform-level, no tenant context)."""
    result: UUID | None = await conn.fetchval("SELECT platform.find_organization_id($1)", slug)
    return result


async def create_organization(
    pool: Pool,
    *,
    slug: str,
    name: str,
    admin_email: str,
    idp_organization_id: str,
    domain_key: str = "generic",
    settings: dict[str, Any] | None = None,
) -> OrganizationCreated:
    """Create an organization, its root org unit and invited first admin in one transaction.

    Idempotent on `slug`: a second call with an existing slug changes nothing and returns
    `created=False` with the existing organization id (and the matching admin's member id, if an
    admin with `admin_email` already exists in it).
    """
    async with platform_transaction(pool) as conn:
        existing_id = await find_organization_id_by_slug(conn, slug)
    if existing_id is not None:
        async with tenant_transaction(pool, existing_id) as conn:
            admin_id: UUID | None = await conn.fetchval(
                "SELECT id FROM public.members WHERE organization_id = $1 AND email = $2",
                existing_id,
                admin_email,
            )
        return OrganizationCreated(existing_id, admin_id, created=False)

    org_id, unit_id, admin_id = uuid7(), uuid7(), uuid7()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.organizations "
            "(id, slug, name, idp_organization_id, domain_key, settings) "
            "VALUES ($1, $2, $3, $4, $5, $6::jsonb)",
            org_id,
            slug,
            name,
            idp_organization_id,
            domain_key,
            json.dumps(settings or {}),
        )
        await conn.execute(
            "INSERT INTO public.org_units (id, organization_id, parent_id, path, type, code, name) "
            "VALUES ($1, $2, NULL, $3::ltree, $4, $3, $5)",
            unit_id,
            org_id,
            ROOT_ORG_UNIT_CODE,
            ROOT_ORG_UNIT_TYPE,
            name,
        )
        await conn.execute(
            "INSERT INTO public.members "
            "(id, organization_id, idp_subject, email, display_name, primary_org_unit_id, status) "
            "VALUES ($1, $2, $3, $4, $4, $5, 'invited')",
            admin_id,
            org_id,
            _pending_idp_subject(admin_email),
            admin_email,
            unit_id,
        )
        await conn.execute(
            "INSERT INTO public.role_grants (id, organization_id, member_id, role_key, scope_type, source) "
            "VALUES ($1, $2, $3, $4, 'organization', 'manual')",
            uuid7(),
            org_id,
            admin_id,
            ADMIN_ROLE_KEY,
        )
        await record_audit_event(
            conn,
            organization_id=org_id,
            action="organization.create",
            entity_type="organization",
            entity_id=org_id,
            after_state={"slug": slug, "organization_name": name, "email": admin_email},
        )
        await conn.execute(
            "INSERT INTO public.outbox "
            "(id, organization_id, event_type, aggregate_type, aggregate_id, payload) "
            "VALUES ($1, $2, 'organization.created', 'organization', $3, $4::jsonb)",
            uuid7(),
            org_id,
            org_id,
            json.dumps({"slug": slug}),
        )
    return OrganizationCreated(org_id, admin_id, created=True)


def _pending_idp_subject(admin_email: str) -> str:
    """Placeholder until the invited admin's first sign-in links the real IdP subject (P5-03)."""
    return f"pending-invite:{admin_email}"
