# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Bulk import against a real PostgreSQL: preview writes nothing, commit is all or nothing,
repeated import is idempotent (M1.4-T7).

Each test creates its own organization rather than reusing `isolation_db.org_a`/`org_b` (shared
session-scoped fixtures other isolation tests also use).
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from pg_harness import PoolFactory

from app.core.db import Pool, tenant_transaction
from app.core.problems import ValidationFailedError
from app.modules.organization.bulk_import import ImportRequest, MemberRow, OrgUnitRow, TeamRow, run_import


async def _create_org(pool: Pool) -> UUID:
    org_id = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.organizations"
            " (id, slug, name, idp_organization_id, domain_key, settings)"
            " VALUES ($1, $2, 'Import Test Org', $3, 'generic', '{}'::jsonb)",
            org_id,
            f"import-{org_id.hex[:12]}",
            f"idp-import-{uuid4().hex[:12]}",
        )
    return org_id


def _valid_request() -> ImportRequest:
    return ImportRequest(
        org_units=[
            OrgUnitRow(code="hq", name="Headquarters", type="division"),
            OrgUnitRow(code="svc", name="Service Desk", type="unit", parent_code="hq"),
        ],
        teams=[TeamRow(code="team-a", name="Team Alpha", type="maintenance", owning_org_unit_code="svc")],
        members=[MemberRow(email="a@test.example", display_name="A", primary_org_unit_code="svc")],
    )


async def test_preview_validates_and_writes_nothing(make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    async with tenant_transaction(pool, org_id) as conn:
        result = await run_import(conn, organization_id=org_id, data=_valid_request(), dry_run=True)
    assert result.as_dict() == {
        "org_units": {"created": 2, "skipped": 0},
        "teams": {"created": 1, "skipped": 0},
        "members": {"created": 1, "skipped": 0},
    }
    async with tenant_transaction(pool, org_id) as conn:
        assert (
            await conn.fetchval("SELECT count(*) FROM public.org_units WHERE organization_id = $1", org_id)
            == 0
        )
        assert (
            await conn.fetchval("SELECT count(*) FROM public.teams WHERE organization_id = $1", org_id) == 0
        )
        assert (
            await conn.fetchval("SELECT count(*) FROM public.members WHERE organization_id = $1", org_id) == 0
        )


async def test_commit_creates_everything_in_one_transaction(make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    async with tenant_transaction(pool, org_id) as conn:
        result = await run_import(conn, organization_id=org_id, data=_valid_request(), dry_run=False)
    assert result.org_units.created == 2
    assert result.teams.created == 1
    assert result.members.created == 1

    async with tenant_transaction(pool, org_id) as conn:
        svc_path = await conn.fetchval(
            "SELECT path FROM public.org_units WHERE organization_id = $1 AND code = 'svc'", org_id
        )
        assert str(svc_path) == "hq.svc"
        team_owner = await conn.fetchval(
            "SELECT ou.code FROM public.teams t JOIN public.org_units ou ON ou.id = t.owning_org_unit_id"
            " WHERE t.organization_id = $1 AND t.code = 'team-a'",
            org_id,
        )
        assert team_owner == "svc"
        member = await conn.fetchrow(
            "SELECT status, idp_subject FROM public.members WHERE organization_id = $1 AND email = $2",
            org_id,
            "a@test.example",
        )
        assert member is not None
        assert member["status"] == "invited"
        assert member["idp_subject"] == "pending-invite:a@test.example"

        action = await conn.fetchval(
            "SELECT action FROM public.audit_events WHERE organization_id = $1 AND entity_type = 'import'",
            org_id,
        )
        assert action == "import.commit"
        event_type = await conn.fetchval(
            "SELECT event_type FROM public.outbox WHERE organization_id = $1 AND aggregate_type = 'import'",
            org_id,
        )
        assert event_type == "import.committed"


async def test_one_bad_row_rolls_back_the_whole_commit(make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    bad_request = ImportRequest(
        org_units=[OrgUnitRow(code="hq", name="Headquarters", type="division")],
        teams=[
            TeamRow(
                code="team-a", name="Team Alpha", type="maintenance", owning_org_unit_code="does-not-exist"
            )
        ],
    )
    with pytest.raises(ValidationFailedError) as excinfo:
        async with tenant_transaction(pool, org_id) as conn:
            await run_import(conn, organization_id=org_id, data=bad_request, dry_run=False)
    assert excinfo.value.errors is not None
    assert any(e.field == "teams[0].owning_org_unit_code" for e in excinfo.value.errors)

    async with tenant_transaction(pool, org_id) as conn:
        # the valid org_units row must NOT have been kept despite being processed first
        assert (
            await conn.fetchval("SELECT count(*) FROM public.org_units WHERE organization_id = $1", org_id)
            == 0
        )


async def test_repeated_commit_is_idempotent(make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    async with tenant_transaction(pool, org_id) as conn:
        await run_import(conn, organization_id=org_id, data=_valid_request(), dry_run=False)
    async with tenant_transaction(pool, org_id) as conn:
        second = await run_import(conn, organization_id=org_id, data=_valid_request(), dry_run=False)
    assert second.as_dict() == {
        "org_units": {"created": 0, "skipped": 2},
        "teams": {"created": 0, "skipped": 1},
        "members": {"created": 0, "skipped": 1},
    }
    async with tenant_transaction(pool, org_id) as conn:
        assert (
            await conn.fetchval("SELECT count(*) FROM public.org_units WHERE organization_id = $1", org_id)
            == 2
        )
        assert (
            await conn.fetchval("SELECT count(*) FROM public.members WHERE organization_id = $1", org_id) == 1
        )


async def test_duplicate_code_within_the_same_import_is_an_error(make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    request = ImportRequest(
        org_units=[
            OrgUnitRow(code="hq", name="Headquarters", type="division"),
            OrgUnitRow(code="hq", name="Headquarters Again", type="division"),
        ]
    )
    with pytest.raises(ValidationFailedError) as excinfo:
        async with tenant_transaction(pool, org_id) as conn:
            await run_import(conn, organization_id=org_id, data=request, dry_run=True)
    assert any("duplicate code" in e.message for e in excinfo.value.errors or [])


async def test_row_limit_is_enforced(make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    too_many = ImportRequest(
        org_units=[OrgUnitRow(code=f"u{i}", name=f"Unit {i}", type="division") for i in range(501)]
    )
    with pytest.raises(ValidationFailedError, match="limit"):
        async with tenant_transaction(pool, org_id) as conn:
            await run_import(conn, organization_id=org_id, data=too_many, dry_run=True)
