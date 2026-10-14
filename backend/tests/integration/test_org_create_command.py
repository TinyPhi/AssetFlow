# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""`assetflow org create`: first run creates everything, a second run changes nothing (M1.4-T2)."""

from __future__ import annotations

import json
from uuid import uuid4

from pg_harness import PoolFactory

from app.core.db import tenant_transaction
from app.modules.organization.service import create_organization


def _slug() -> str:
    return f"org-{uuid4().hex[:10]}"


async def test_first_run_creates_organization_root_unit_admin_and_events(make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    slug, email = _slug(), "admin@example.test"
    result = await create_organization(
        pool, slug=slug, name="Example Co", admin_email=email, idp_organization_id=f"idp-{slug}"
    )
    assert result.created is True
    org_id = result.organization_id

    async with tenant_transaction(pool, org_id) as conn:
        org = await conn.fetchrow(
            "SELECT name, domain_key, status FROM public.organizations WHERE id = $1", org_id
        )
        assert org is not None
        assert (org["name"], org["domain_key"], org["status"]) == ("Example Co", "generic", "active")

        unit = await conn.fetchrow(
            "SELECT parent_id, type, code, name FROM public.org_units WHERE organization_id = $1", org_id
        )
        assert unit is not None
        assert (unit["parent_id"], unit["type"], unit["code"], unit["name"]) == (
            None,
            "root",
            "root",
            "Example Co",
        )

        member = await conn.fetchrow(
            "SELECT id, email, status, idp_subject FROM public.members WHERE organization_id = $1", org_id
        )
        assert member is not None
        assert member["id"] == result.admin_member_id
        assert (member["email"], member["status"]) == (email, "invited")
        assert member["idp_subject"] == f"pending-invite:{email}"

        grant = await conn.fetchrow(
            "SELECT role_key, scope_type, scope_id FROM public.role_grants"
            " WHERE organization_id = $1 AND member_id = $2",
            org_id,
            result.admin_member_id,
        )
        assert grant is not None
        assert (grant["role_key"], grant["scope_type"], grant["scope_id"]) == ("admin", "organization", None)

        event = await conn.fetchrow(
            "SELECT action, after_state FROM public.audit_events WHERE organization_id = $1", org_id
        )
        assert event is not None
        assert event["action"] == "organization.create"
        after = json.loads(event["after_state"])
        assert after == {"slug": slug, "organization_name": "Example Co", "email": "[REDACTED]"}

        personal = await conn.fetchval(
            "SELECT field_value FROM public.audit_personal_values"
            " WHERE organization_id = $1 AND field_name = 'email'",
            org_id,
        )
        assert personal == email

        outbox = await conn.fetchrow(
            "SELECT event_type, aggregate_type, aggregate_id FROM public.outbox WHERE organization_id = $1",
            org_id,
        )
        assert outbox is not None
        assert (outbox["event_type"], outbox["aggregate_type"], outbox["aggregate_id"]) == (
            "organization.created",
            "organization",
            org_id,
        )


async def test_second_run_with_the_same_slug_changes_nothing(make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    slug, email = _slug(), "admin@example.test"
    first = await create_organization(
        pool, slug=slug, name="Example Co", admin_email=email, idp_organization_id=f"idp-{slug}"
    )
    assert first.created is True

    second = await create_organization(
        pool,
        slug=slug,
        name="A Different Name",
        admin_email="someone-else@example.test",
        idp_organization_id="a-different-idp-org",
    )
    assert second.created is False
    assert second.organization_id == first.organization_id
    assert second.admin_member_id is None  # no member with that (different) email exists yet

    third = await create_organization(
        pool, slug=slug, name="A Different Name", admin_email=email, idp_organization_id="a-different-idp-org"
    )
    assert third.created is False
    assert third.admin_member_id == first.admin_member_id

    async with tenant_transaction(pool, first.organization_id) as conn:
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM public.organizations WHERE id = $1", first.organization_id
            )
            == 1
        )
        assert (
            await conn.fetchval("SELECT name FROM public.organizations WHERE id = $1", first.organization_id)
            == "Example Co"
        )
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM public.org_units WHERE organization_id = $1", first.organization_id
            )
            == 1
        )
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM public.members WHERE organization_id = $1", first.organization_id
            )
            == 1
        )
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM public.role_grants WHERE organization_id = $1", first.organization_id
            )
            == 1
        )
