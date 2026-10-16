# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""E2E: a member's notification preferences decide which channels an event uses (§B6.3 rule 7, M1.5-T7).

The real app, outbox dispatcher and automation subscriber run against real PostgreSQL. Whether an
email is queued is read from the delivery log (`notification_deliveries`), which is exactly what the
sender sends from, so no mail server is needed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx
import pytest
from pg_harness import IsolationDb, PoolFactory

from app.channels.email import EmailChannel
from app.channels.inapp import InAppChannel
from app.channels.registry import ChannelRegistry
from app.core.db import Pool, tenant_transaction
from app.engines.automation import subscriber as automation_subscriber
from app.main import create_app
from app.providers.auth.mock import MockAuthProvider
from app.providers.context import ProviderContext
from app.providers.secrets.file import FileSecretsProvider
from app.providers.telemetry.noop import NoOpTelemetryProvider
from workers.outbox_dispatcher import DispatcherOptions, run_once
from workers.subscribers import default_registry

PREFS = "/api/v1/me/notification-preferences"
OPTIONS = DispatcherOptions(batch_size=50, reclaim_after_seconds=300, max_attempts=3)
ADDED = "team_member.added"
TEMPLATE = (
    "domain_key: test-neutral\n"
    "automations:\n"
    "  - when: team_member.added\n"
    "    then:\n"
    "      recipients:\n"
    "        - holder\n"
    "      channels:\n"
    "        - inapp\n"
    "        - email\n"
    "      template: team-member-added\n"
    "  - when: team_member.updated\n"
    "    then:\n"
    "      recipients:\n"
    "        - role:admin@organization\n"
    "      channels:\n"
    "        - inapp\n"
    "      template: team-member-added\n"
    "      mandatory: true\n"
)


@pytest.fixture(autouse=True)
def _domains_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    domains = tmp_path / "domains"
    domains.mkdir()
    (domains / "test-neutral.yaml").write_text(TEMPLATE, encoding="utf-8")
    monkeypatch.setattr(automation_subscriber, "DOMAINS_DIR", domains)


class _Registry:
    def __init__(self, secrets: FileSecretsProvider) -> None:
        self.auth = MockAuthProvider(ProviderContext("test", "auth", Path()))
        self.telemetry = NoOpTelemetryProvider()
        self.secrets = secrets


@pytest.fixture
async def client(make_pool: PoolFactory, tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    context = ProviderContext(env="test", pillar="secrets", base_dir=tmp_path)
    app = create_app()
    app.state.registry = _Registry(FileSecretsProvider.from_settings({"directory": "secrets"}, context))
    app.state.pool = await make_pool("api")
    channels = ChannelRegistry()
    channels.register(InAppChannel)
    channels.register(EmailChannel)
    app.state.channel_registry = channels
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def admin_db(isolation_db: IsolationDb) -> AsyncIterator[asyncpg.Connection[asyncpg.Record]]:
    conn = await asyncpg.connect(isolation_db.admin_dsn)
    yield conn
    for table in (
        "notification_deliveries",
        "notifications",
        "notification_preferences",
        "notification_channels",
    ):
        await conn.execute(f"DELETE FROM public.{table}")  # noqa: S608 - fixed table names
    await conn.execute("DELETE FROM public.outbox WHERE event_type LIKE 'notification_%'")
    await conn.close()


async def _org(pool: Pool) -> tuple[UUID, UUID]:
    org_id, admin_id = uuid4(), uuid4()
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
            "VALUES ($1, $2, $3, 'active', $4, 'Admin User')",
            admin_id,
            org_id,
            f"admin-{admin_id.hex[:8]}@example.test",
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


async def _member(pool: Pool, org_id: UUID) -> UUID:
    member_id = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.members (id, organization_id, email, status, idp_subject, display_name) "
            "VALUES ($1, $2, $3, 'active', $4, 'A Member')",
            member_id,
            org_id,
            f"m-{member_id.hex[:8]}@example.test",
            f"sub-{member_id}",
        )
    return member_id


def _as(org_id: UUID, member_id: UUID, role: str) -> dict[str, str]:
    return {
        "x-organization-id": str(org_id),
        "x-member-id": str(member_id),
        "x-role": role,
        "x-scope-type": "organization",
    }


def _cell(matrix: dict[str, Any], event: str, channel: str) -> dict[str, Any]:
    (found,) = (e for e in matrix["events"] if e["event_type"] == event)
    (cell,) = (c for c in found["channels"] if c["channel_key"] == channel)
    return cell  # type: ignore[no-any-return]


async def _put(
    client: httpx.AsyncClient, headers: dict[str, str], *changes: dict[str, Any]
) -> httpx.Response:
    return await client.put(PREFS, headers=headers, json={"changes": list(changes)})


async def _add_to_new_team(
    client: httpx.AsyncClient, admin: dict[str, str], member_id: UUID, worker: Pool, n: int
) -> None:
    team = await client.post(
        "/api/v1/teams", headers=admin, json={"code": f"crew-{n}", "name": f"Crew {n}", "type": "crew"}
    )
    added = await client.post(
        f"/api/v1/teams/{team.json()['data']['id']}/members",
        headers=admin,
        json={"member_id": str(member_id), "team_role": "member"},
    )
    assert added.status_code == 201
    for _ in range(10):  # a hard cap: a stuck test must fail, not hang
        if await run_once(worker, default_registry(), "e2e-worker", OPTIONS) == 0:
            return
    raise AssertionError("outbox did not drain")


async def test_a_member_chooses_the_channels_and_the_event_follows_the_choice(
    client: httpx.AsyncClient, make_pool: PoolFactory, admin_db: asyncpg.Connection[asyncpg.Record]
) -> None:
    api, worker = await make_pool("api"), await make_pool("worker")
    org, admin_id = await _org(api)
    admin = _as(org, admin_id, "admin")
    member_id = await _member(api, org)
    me = _as(org, member_id, "member")
    assert (
        await client.post(
            "/api/v1/notification-channels/installations", headers=admin, json={"channel_key": "email"}
        )
    ).status_code == 201

    matrix = (await client.get(PREFS, headers=me)).json()["data"]
    assert matrix["channels"] == ["email", "inapp"]
    assert _cell(matrix, ADDED, "email") == {
        "channel_key": "email",
        "enabled": True,
        "version": 0,
        "locked": False,
    }
    assert _cell(matrix, ADDED, "inapp")["locked"] is False
    assert _cell(matrix, "team_member.updated", "inapp")["locked"] is True  # a mandatory rule

    off = await _put(client, me, {"event_type": ADDED, "channel_key": "email", "enabled": False})
    assert off.status_code == 200, off.text
    assert _cell(off.json()["data"], ADDED, "email") == {
        "channel_key": "email",
        "enabled": False,
        "version": 1,
        "locked": False,
    }

    await _add_to_new_team(client, admin, member_id, worker, 1)
    inbox = (await client.get("/api/v1/notifications", headers=me)).json()["data"]["items"]
    assert len(inbox) == 1  # the in-app notice still arrives
    assert (
        await admin_db.fetchval(
            "SELECT count(*) FROM public.notification_deliveries "
            "WHERE channel_key = 'email' AND recipient_member_id = $1",
            member_id,
        )
        == 0
    )

    on = await _put(client, me, {"event_type": ADDED, "channel_key": "email", "enabled": True, "version": 1})
    assert on.status_code == 200
    assert _cell(on.json()["data"], ADDED, "email")["enabled"] is True
    await _add_to_new_team(client, admin, member_id, worker, 2)
    assert (
        await admin_db.fetchval(
            "SELECT count(*) FROM public.notification_deliveries "
            "WHERE channel_key = 'email' AND recipient_member_id = $1",
            member_id,
        )
        == 1
    )
    assert len((await client.get("/api/v1/notifications", headers=me)).json()["data"]["items"]) == 2


async def test_in_app_cannot_be_switched_off_for_a_mandatory_event(
    client: httpx.AsyncClient, make_pool: PoolFactory, admin_db: asyncpg.Connection[asyncpg.Record]
) -> None:
    api = await make_pool("api")
    org, _ = await _org(api)
    me = _as(org, await _member(api, org), "member")
    locked = await _put(
        client, me, {"event_type": "team_member.updated", "channel_key": "inapp", "enabled": False}
    )
    assert (locked.status_code, locked.json()["code"]) == (422, "notification.preference_locked")
    assert await admin_db.fetchval("SELECT count(*) FROM public.notification_preferences") == 0
    still_on = await _put(
        client, me, {"event_type": "team_member.updated", "channel_key": "inapp", "enabled": True}
    )
    assert still_on.status_code == 200


async def test_stale_versions_unknown_cells_and_duplicates_are_refused(
    client: httpx.AsyncClient, make_pool: PoolFactory, admin_db: asyncpg.Connection[asyncpg.Record]
) -> None:
    api = await make_pool("api")
    org, _ = await _org(api)
    me = _as(org, await _member(api, org), "member")
    cell = {"event_type": ADDED, "channel_key": "inapp"}
    assert (await _put(client, me, {**cell, "enabled": False})).status_code == 200

    stale = await _put(client, me, {**cell, "enabled": True, "version": 0})
    assert (stale.status_code, stale.json()["code"]) == (409, "notification_preference.version_conflict")
    missing = await _put(client, me, {**cell, "enabled": True})
    assert missing.status_code == 409  # a stored cell needs the version the caller saw
    assert (await _put(client, me, {**cell, "enabled": True, "version": 1})).status_code == 200

    for bad in (
        [{"event_type": "no.such.event", "channel_key": "inapp", "enabled": False}],
        [{"event_type": ADDED, "channel_key": "webhook", "enabled": False}],
        [{**cell, "enabled": False}, {**cell, "enabled": True}],
        [],
    ):
        res = await client.put(PREFS, headers=me, json={"changes": bad})
        assert res.status_code == 422, (bad, res.text)


async def test_a_change_is_audited_once_and_a_no_op_is_not(
    client: httpx.AsyncClient, make_pool: PoolFactory, admin_db: asyncpg.Connection[asyncpg.Record]
) -> None:
    api = await make_pool("api")
    org, _ = await _org(api)
    member_id = await _member(api, org)
    me = _as(org, member_id, "member")
    change = {"event_type": ADDED, "channel_key": "inapp", "enabled": False}
    await _put(client, me, change)
    await _put(client, me, {**change, "version": 1})  # already off: nothing to do
    events = await admin_db.fetch(
        "SELECT action, after_state FROM public.audit_events WHERE entity_id = $1", member_id
    )
    assert [e["action"] for e in events] == ["notification_preferences.changed"]
    assert (
        await admin_db.fetchval(
            "SELECT count(*) FROM public.outbox WHERE event_type = 'notification_preferences.changed' "
            "AND aggregate_id = $1",
            member_id,
        )
        == 1
    )


async def test_each_member_has_their_own_matrix_and_no_route_reaches_anothers(
    client: httpx.AsyncClient, make_pool: PoolFactory, admin_db: asyncpg.Connection[asyncpg.Record]
) -> None:
    api = await make_pool("api")
    org_a, org_b = await _org(api), await _org(api)
    ada, bob = await _member(api, org_a[0]), await _member(api, org_a[0])
    other_org_member = await _member(api, org_b[0])
    await _put(
        client, _as(org_a[0], ada, "member"), {"event_type": ADDED, "channel_key": "inapp", "enabled": False}
    )

    assert (
        _cell((await client.get(PREFS, headers=_as(org_a[0], ada, "member"))).json()["data"], ADDED, "inapp")[
            "enabled"
        ]
        is False
    )
    for other in (_as(org_a[0], bob, "member"), _as(org_b[0], other_org_member, "member")):
        assert (
            _cell((await client.get(PREFS, headers=other)).json()["data"], ADDED, "inapp")["enabled"] is True
        )
    assert (
        await admin_db.fetchval(
            "SELECT count(*) FROM public.notification_preferences WHERE member_id = $1", bob
        )
        == 0
    )
    # the path has no member id to put in: "me" is the only form
    assert (
        await client.get(
            f"/api/v1/members/{ada}/notification-preferences", headers=_as(org_a[0], bob, "member")
        )
    ).status_code == 404


async def test_a_caller_without_the_permission_gets_404_to_read_and_403_to_change(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    api = await make_pool("api")
    org, _ = await _org(api)
    technician = _as(org, await _member(api, org), "technician")
    assert (await client.get(PREFS, headers=technician)).status_code == 404
    denied = await _put(client, technician, {"event_type": ADDED, "channel_key": "inapp", "enabled": False})
    assert denied.status_code == 403
    assert (await client.get(PREFS)).status_code == 401
