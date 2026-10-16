# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Organization settings against a real PostgreSQL: validation, merge, audit (M1.4-T9).

Each test creates its own organization rather than reusing `isolation_db.org_a`/`org_b` (shared
session-scoped fixtures other isolation tests also use).
"""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import asyncpg
import pytest
from pg_harness import PoolFactory

from app.core.db import Pool, platform_transaction, tenant_transaction
from app.core.problems import ValidationFailedError
from app.modules.organization.settings import get_settings, update_settings


async def _create_org(pool: Pool, *, settings: dict[str, object] | None = None) -> UUID:
    org_id = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.organizations"
            " (id, slug, name, idp_organization_id, domain_key, settings)"
            " VALUES ($1, $2, 'Settings Test Org', $3, 'generic', $4::jsonb)",
            org_id,
            f"settings-{org_id.hex[:12]}",
            f"idp-settings-{uuid4().hex[:12]}",
            json.dumps(settings or {}),
        )
    return org_id


async def test_get_settings_on_a_fresh_organization_is_empty(make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    async with tenant_transaction(pool, org_id) as conn:
        assert await get_settings(conn, org_id) == {}


async def test_update_merges_without_dropping_unrelated_keys(make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool, settings={"locale": "en-US", "currency": "USD"})
    async with tenant_transaction(pool, org_id) as conn:
        after = await update_settings(conn, org_id, {"locale": "fr-FR"})
        assert after == {"locale": "fr-FR", "currency": "USD"}
        assert await get_settings(conn, org_id) == after


async def test_update_rejects_an_unknown_key(make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    async with tenant_transaction(pool, org_id) as conn:
        with pytest.raises(ValidationFailedError, match="unknown setting"):
            await update_settings(conn, org_id, {"made_up_key": "x"})


async def test_update_rejects_an_invalid_provisioning_policy(make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    async with tenant_transaction(pool, org_id) as conn:
        with pytest.raises(ValidationFailedError, match="provisioning"):
            await update_settings(conn, org_id, {"provisioning": "whatever"})


async def test_update_rejects_a_calendar_from_another_organization(make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_a, org_b = await _create_org(pool), await _create_org(pool)
    calendar_id = uuid4()
    async with tenant_transaction(pool, org_b) as conn:
        await conn.execute(
            "INSERT INTO public.working_calendars (id, organization_id, name) VALUES ($1, $2, 'Default')",
            calendar_id,
            org_b,
        )
    async with tenant_transaction(pool, org_a) as conn:
        with pytest.raises(ValidationFailedError, match="default_calendar_id"):
            await update_settings(conn, org_a, {"default_calendar_id": calendar_id})


async def test_update_accepts_a_calendar_from_the_same_organization(make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    calendar_id = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.working_calendars (id, organization_id, name) VALUES ($1, $2, 'Default')",
            calendar_id,
            org_id,
        )
        after = await update_settings(conn, org_id, {"default_calendar_id": calendar_id})
        assert after["default_calendar_id"] == str(calendar_id)


async def test_update_writes_one_audit_event_with_old_and_new_values_and_an_outbox_row(
    make_pool: PoolFactory,
) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool, settings={"locale": "en-US"})
    actor_id = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await update_settings(conn, org_id, {"locale": "de-DE"}, actor_member_id=actor_id)

        event = await conn.fetchrow(
            "SELECT action, actor_member_id, before_state, after_state FROM public.audit_events"
            " WHERE organization_id = $1 AND entity_type = 'organization' AND entity_id = $1",
            org_id,
        )
        assert event is not None
        assert event["action"] == "organization.settings_update"
        assert event["actor_member_id"] == actor_id
        assert json.loads(event["before_state"]) == {"locale": "en-US"}
        assert json.loads(event["after_state"]) == {"locale": "de-DE"}

        outbox_type = await conn.fetchval(
            "SELECT event_type FROM public.outbox WHERE organization_id = $1 AND aggregate_id = $1", org_id
        )
        assert outbox_type == "organization.settings_updated"


async def test_worker_and_readonly_still_cannot_update_organizations(make_pool: PoolFactory) -> None:
    """The 0008 grant is scoped to assetflow_api only."""
    org_id = await _create_org(await make_pool("api"))
    for kind in ("worker", "readonly"):
        pool = await make_pool(kind)
        async with platform_transaction(pool) as conn:
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await conn.execute(
                    "UPDATE public.organizations SET settings = '{}'::jsonb WHERE id = $1", org_id
                )
