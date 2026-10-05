# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Catalog reference data API: categories, custom field definitions, manufacturers, suppliers
(M2.1-T1/T2 data, §B8.1, P8-06): permission, version conflict, archive-blocked, type-change-blocked,
audit+outbox, isolation and seed idempotency, all against a real disposable PostgreSQL."""

from __future__ import annotations

from uuid import UUID, uuid4

from app.core.db import Pool, tenant_transaction
from app.modules.organization.modules import install_module


async def _create_org(pool: Pool, *, domain_key: str = "generic") -> UUID:
    org_id = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.organizations"
            " (id, slug, name, idp_organization_id, domain_key, settings)"
            " VALUES ($1, $2, 'Catalog API Org', $3, $4, '{}'::jsonb)",
            org_id,
            f"catalog-api-{org_id.hex[:12]}",
            f"idp-catalog-api-{uuid4().hex[:12]}",
            domain_key,
        )
        await install_module(conn, org_id, "assets")
    return org_id
