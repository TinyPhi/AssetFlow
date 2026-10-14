# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""E2E API tests for the in-app inbox (§B4.5, §B6.3, M1.5-T3).

An organization event (adding a team member) runs through the real API, the real outbox dispatcher
(`workers.outbox_dispatcher.run_once`, run inline rather than as a separate process - §C8.6's
"the app under test also runs the worker" in spirit, without a real subprocess) and the real
automation subscriber, landing in the new member's inbox exactly as it would in production.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from pg_harness import PoolFactory

from app.core.db import Pool, tenant_transaction
from app.engines.automation import subscriber as automation_subscriber
from app.main import create_app
from app.providers.auth.mock import MockAuthProvider
from app.providers.context import ProviderContext
from app.providers.telemetry.noop import NoOpTelemetryProvider
from workers.outbox_dispatcher import DispatcherOptions, run_once
from workers.subscribers import default_registry

FIXTURE_TEMPLATE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "domains" / "test-neutral.yaml"
).read_text(encoding="utf-8")

OPTIONS = DispatcherOptions(batch_size=50, reclaim_after_seconds=300, max_attempts=3)


@pytest.fixture(autouse=True)
def _domains_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the automation subscriber at a throwaway copy of the test fixture domain template,
    instead of the real `config/domains/` (which has no templates until master Phase 2)."""
    domains = tmp_path / "domains"
    domains.mkdir()
    (domains / "test-neutral.yaml").write_text(FIXTURE_TEMPLATE, encoding="utf-8")
    monkeypatch.setattr(automation_subscriber, "DOMAINS_DIR", domains)


class _Registry:
    def __init__(self) -> None:
        self.auth = MockAuthProvider(ProviderContext("test", "auth", Path()))
        self.telemetry = NoOpTelemetryProvider()


async def _make_client(pool: Pool) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()
    app.state.registry = _Registry()
    app.state.pool = pool
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def client(make_pool: PoolFactory) -> AsyncIterator[httpx.AsyncClient]:
    pool = await make_pool("api")
    async for c in _make_client(pool):
        yield c


async def _create_org(pool: Pool) -> tuple[UUID, UUID]:
    """A fresh organization with `domain_key = test-neutral` and one admin member."""
    org_id = uuid4()
    admin_id = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.organizations (id, slug, name, domain_key, idp_organization_id, status) "
            "VALUES ($1, $2, 'Test Org', 'test-neutral', $3, 'active')",
            org_id,
            f"org-{org_id.hex[:8]}",
            f"idp-{org_id.hex[:12]}",
        )
        await conn.execute(
            "INSERT INTO public.members (id, organization_id, email, status, idp_subject, display_name) "
            "VALUES ($1, $2, 'admin@example.test', 'active', $3, 'Admin User')",
            admin_id,
            org_id,
            f"sub-{admin_id}",
        )
        await conn.execute(
            "INSERT INTO public.role_grants (id, organization_id, member_id, role_key, scope_type) "
            "VALUES ($1, $2, $3, 'admin', 'organization')",
            uuid4(),
            org_id,
            admin_id,
        )
    return org_id, admin_id


def _headers(org_id: UUID, member_id: UUID, role: str = "admin") -> dict[str, str]:
    return {
        "x-organization-id": str(org_id),
        "x-member-id": str(member_id),
        "x-role": role,
        "x-scope-type": "organization",
    }


def _member_headers(org_id: UUID, member_id: UUID) -> dict[str, str]:
    return _headers(org_id, member_id, role="member")


async def _drain_outbox(pool: Pool) -> None:
    """Run the real outbox dispatcher inline until nothing is left to claim."""
    registry = default_registry()
    for _ in range(10):  # a hard cap: a stuck test must fail, not hang
        handled = await run_once(pool, registry, "test-worker", OPTIONS)
        if handled == 0:
            return
    raise AssertionError("outbox did not drain within 10 batches")


async def test_adding_a_team_member_delivers_an_in_app_notice(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id, admin_id = await _create_org(pool)
    admin_headers = _headers(org_id, admin_id)

    team_res = await client.post(
        "/api/v1/teams",
        headers=admin_headers,
        json={"code": "crew-1", "name": "Crew One", "type": "crew"},
    )
    assert team_res.status_code == 201
    team_id = team_res.json()["data"]["id"]

    new_member_id = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.members (id, organization_id, email, status, idp_subject, display_name) "
            "VALUES ($1, $2, 'new@example.test', 'active', $3, 'New Member')",
            new_member_id,
            org_id,
            f"sub-{new_member_id}",
        )

    add_res = await client.post(
        f"/api/v1/teams/{team_id}/members",
        headers=admin_headers,
        json={"member_id": str(new_member_id), "team_role": "member"},
    )
    assert add_res.status_code == 201

    worker_pool = await make_pool("worker")
    await _drain_outbox(worker_pool)

    member_headers = _member_headers(org_id, new_member_id)

    list_res = await client.get("/api/v1/notifications", headers=member_headers)
    assert list_res.status_code == 200
    items = list_res.json()["data"]["items"]
    assert len(items) == 1
    notification_id = items[0]["id"]
    assert items[0]["read_at"] is None

    unread_res = await client.get("/api/v1/notifications/unread-count", headers=member_headers)
    assert unread_res.json()["data"]["unread"] == 1

    read_res = await client.post(f"/api/v1/notifications/{notification_id}/read", headers=member_headers)
    assert read_res.status_code == 200
    assert read_res.json()["data"]["changed"] is True

    unread_after = await client.get("/api/v1/notifications/unread-count", headers=member_headers)
    assert unread_after.json()["data"]["unread"] == 0

    # Reading the same notice again changes nothing (idempotent on the member's own side too).
    read_again = await client.post(f"/api/v1/notifications/{notification_id}/read", headers=member_headers)
    assert read_again.json()["data"]["changed"] is False

    read_all_res = await client.post("/api/v1/notifications/read-all", headers=member_headers)
    assert read_all_res.json()["data"]["changed"] == 0  # already all read


async def test_updated_since_returns_only_newer_rows(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id, admin_id = await _create_org(pool)
    admin_headers = _headers(org_id, admin_id)
    member_headers = _member_headers(org_id, admin_id)
    worker_pool = await make_pool("worker")

    # Two separate teams, admin_id added to each in turn, so admin_id ends up with two notices at
    # two different timestamps - draining the outbox between them keeps the order deterministic.
    first_team = await client.post(
        "/api/v1/teams", headers=admin_headers, json={"code": "crew-2a", "name": "Crew Two A", "type": "crew"}
    )
    await client.post(
        f"/api/v1/teams/{first_team.json()['data']['id']}/members",
        headers=admin_headers,
        json={"member_id": str(admin_id), "team_role": "lead"},
    )
    await _drain_outbox(worker_pool)
    first_list = await client.get("/api/v1/notifications", headers=member_headers)
    first_items = first_list.json()["data"]["items"]
    assert len(first_items) == 1
    cutoff = first_items[0]["updated_at"]

    second_team = await client.post(
        "/api/v1/teams", headers=admin_headers, json={"code": "crew-2b", "name": "Crew Two B", "type": "crew"}
    )
    await client.post(
        f"/api/v1/teams/{second_team.json()['data']['id']}/members",
        headers=admin_headers,
        json={"member_id": str(admin_id), "team_role": "lead"},
    )
    await _drain_outbox(worker_pool)

    all_items = (await client.get("/api/v1/notifications", headers=member_headers)).json()["data"]["items"]
    assert len(all_items) == 2

    since_res = await client.get(
        "/api/v1/notifications", headers=member_headers, params={"updated_since": cutoff}
    )
    newer_items = since_res.json()["data"]["items"]
    assert len(newer_items) == 1  # only the second notice is strictly newer than the first's timestamp
    assert newer_items[0]["id"] not in {item["id"] for item in first_items}


async def test_member_b_cannot_see_or_mark_member_as_notice(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id, admin_id = await _create_org(pool)
    admin_headers = _headers(org_id, admin_id)

    team_res = await client.post(
        "/api/v1/teams", headers=admin_headers, json={"code": "crew-3", "name": "Crew Three", "type": "crew"}
    )
    team_id = team_res.json()["data"]["id"]

    member_a = uuid4()
    member_b = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        for member_id, email in ((member_a, "a@example.test"), (member_b, "b@example.test")):
            await conn.execute(
                "INSERT INTO public.members (id, organization_id, email, status, idp_subject, display_name) "
                "VALUES ($1, $2, $3, 'active', $4, 'Member')",
                member_id,
                org_id,
                email,
                f"sub-{member_id}",
            )

    worker_pool = await make_pool("worker")
    await client.post(
        f"/api/v1/teams/{team_id}/members",
        headers=admin_headers,
        json={"member_id": str(member_a), "team_role": "member"},
    )
    await _drain_outbox(worker_pool)

    a_headers = _member_headers(org_id, member_a)
    b_headers = _member_headers(org_id, member_b)

    a_list = await client.get("/api/v1/notifications", headers=a_headers)
    a_notification_id = a_list.json()["data"]["items"][0]["id"]

    b_list = await client.get("/api/v1/notifications", headers=b_headers)
    assert b_list.json()["data"]["items"] == []

    b_unread = await client.get("/api/v1/notifications/unread-count", headers=b_headers)
    assert b_unread.json()["data"]["unread"] == 0

    b_mark = await client.post(f"/api/v1/notifications/{a_notification_id}/read", headers=b_headers)
    assert b_mark.status_code == 403
