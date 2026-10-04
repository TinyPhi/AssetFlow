# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""E2E: an organization event becomes a signed webhook request (§B6.3, §C8.6, M1.5-T5).

The real app, outbox dispatcher, automation subscriber and notification sender run against real
PostgreSQL. The receiver is a recorded HTTP exchange (`httpx.MockTransport` behind the real egress
client): the test verifies the HMAC, the 5-minute timestamp window and the mapped fields.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx
import pytest
from pg_harness import IsolationDb, PoolFactory

from app.channels.circuit import CircuitRegistry
from app.channels.credentials import ChannelCredentialStore
from app.channels.egress import EgressClient
from app.channels.inapp import InAppChannel
from app.channels.registry import ChannelRegistry
from app.channels.runtime import ChannelRuntime
from app.channels.webhook import WebhookChannel
from app.core.db import Pool, tenant_transaction
from app.engines.automation import subscriber as automation_subscriber
from app.main import create_app
from app.providers.auth.mock import MockAuthProvider
from app.providers.context import ProviderContext
from app.providers.secrets.file import FileSecretsProvider
from app.providers.telemetry.noop import NoOpTelemetryProvider
from workers.notification_sender import SenderDeps
from workers.notification_sender import run_once as run_sender
from workers.outbox_dispatcher import DispatcherOptions
from workers.outbox_dispatcher import run_once as run_dispatcher
from workers.subscribers import default_registry

BASE = "/api/v1/notification-channels"
HOST = "hooks.example.test"
URL = f"https://{HOST}/inbound"
SECRET = "whsec-e2e-throwaway-secret-value"
OPTIONS = DispatcherOptions(batch_size=50, reclaim_after_seconds=300, max_attempts=3)
SETTINGS = {
    "url": URL,
    "events": ["team_member.added"],
    "field_mapping": {"team.id": "team_id", "team.role": "team_role", "member": "member_id"},
}
TEMPLATE = (
    "domain_key: test-neutral\n"
    "automations:\n"
    "  - when: team_member.added\n"
    "    then:\n"
    "      recipients:\n"
    "        - holder\n"
    "      channels:\n"
    "        - inapp\n"
    "        - webhook\n"
    "      template: team-member-added\n"
    "  - when: team.created\n"
    "    then:\n"
    "      recipients:\n"
    "        - role:admin@organization\n"
    "      channels:\n"
    "        - webhook\n"
    "      template: team-member-added\n"
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
def secrets_provider(tmp_path: Path) -> FileSecretsProvider:
    context = ProviderContext(env="test", pillar="secrets", base_dir=tmp_path)
    return FileSecretsProvider.from_settings({"directory": "secrets"}, context)


@pytest.fixture
async def client(
    make_pool: PoolFactory, secrets_provider: FileSecretsProvider
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()
    app.state.registry = _Registry(secrets_provider)
    app.state.pool = await make_pool("api")
    channels = ChannelRegistry()
    channels.register(InAppChannel)
    channels.register(WebhookChannel)
    app.state.channel_registry = channels
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def admin_db(isolation_db: IsolationDb) -> AsyncIterator[asyncpg.Connection[asyncpg.Record]]:
    conn = await asyncpg.connect(isolation_db.admin_dsn)
    yield conn
    await conn.execute("DELETE FROM public.notification_deliveries")
    await conn.execute("DELETE FROM public.notification_channels")
    await conn.execute("DELETE FROM public.notifications")
    await conn.execute("DELETE FROM public.outbox WHERE event_type LIKE 'notification_%'")
    await conn.close()


async def _org_with_admin(pool: Pool) -> tuple[UUID, UUID]:
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


def _as_admin(org_id: UUID, member_id: UUID) -> dict[str, str]:
    return {
        "x-organization-id": str(org_id),
        "x-member-id": str(member_id),
        "x-role": "admin",
        "x-scope-type": "organization",
    }


async def _install(client: httpx.AsyncClient, headers: dict[str, str], **changes: Any) -> httpx.Response:
    body = {"channel_key": "webhook", "settings": SETTINGS, "secrets": {"signing_secret": SECRET}}
    body.update(changes)
    return await client.post(f"{BASE}/installations", headers=headers, json=body)


async def test_installing_a_webhook_adds_its_host_and_never_returns_the_secret(
    client: httpx.AsyncClient,
    make_pool: PoolFactory,
    secrets_provider: FileSecretsProvider,
    isolation_db: IsolationDb,
    admin_db: asyncpg.Connection[asyncpg.Record],
) -> None:
    org_id, admin_id = await _org_with_admin(await make_pool("api"))
    headers = _as_admin(org_id, admin_id)

    created = await _install(client, headers)
    assert created.status_code == 201, created.text
    data = created.json()["data"]
    assert data["allowed_hosts"] == [HOST]
    assert data["secrets"] == {"signing_secret": {"set": True}}
    assert data["settings"]["url"] == URL
    assert "signing_secret" not in data["settings"]
    assert SECRET not in created.text
    assert SECRET not in (await client.get(f"{BASE}/installations/{data['id']}", headers=headers)).text

    audit = await admin_db.fetch(
        "SELECT after_state FROM public.audit_events WHERE entity_id = $1", UUID(data["id"])
    )
    assert SECRET not in json.dumps([dict(a) for a in audit], default=str)
    ref = await admin_db.fetchval(
        "SELECT secret_ref FROM public.notification_channels WHERE id = $1", UUID(data["id"])
    )
    assert await secrets_provider.get_map(ref) == {"signing_secret": SECRET}

    moved = await client.patch(
        f"{BASE}/installations/{data['id']}",
        headers=headers,
        json={"version": 1, "settings": {**SETTINGS, "url": "https://other.example.test/in"}},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["data"]["allowed_hosts"] == [
        "other.example.test"
    ]  # the old host is gone with the old URL


async def test_invalid_webhook_settings_are_refused_when_saved(
    client: httpx.AsyncClient, make_pool: PoolFactory, admin_db: asyncpg.Connection[asyncpg.Record]
) -> None:
    org_id, admin_id = await _org_with_admin(await make_pool("api"))
    headers = _as_admin(org_id, admin_id)
    bad = [
        {"settings": {**SETTINGS, "url": "http://hooks.example.test/in"}},
        {"settings": {**SETTINGS, "url": "https://10.0.0.1/in"}},
        {"settings": {**SETTINGS, "events": ["no.such.event"]}},
        {"settings": {**SETTINGS, "field_mapping": {"x": "not_a_field"}}},
        {"settings": {**SETTINGS, "field_mapping": {"event_id": "team_id"}}},
        {"secrets": {}},
        {"secrets": {"signing_secret": "short"}},
    ]
    for change in bad:
        res = await _install(client, headers, **change)
        assert res.status_code == 422, (change, res.text)
    assert await admin_db.fetchval("SELECT count(*) FROM public.notification_channels") == 0


async def test_an_organization_event_sends_one_signed_request_with_the_mapped_fields(
    client: httpx.AsyncClient,
    make_pool: PoolFactory,
    secrets_provider: FileSecretsProvider,
    admin_db: asyncpg.Connection[asyncpg.Record],
) -> None:
    api, worker = await make_pool("api"), await make_pool("worker")
    org_id, admin_id = await _org_with_admin(api)
    headers = _as_admin(org_id, admin_id)
    assert (await _install(client, headers)).status_code == 201

    team = await client.post(
        "/api/v1/teams", headers=headers, json={"code": "crew-1", "name": "Crew One", "type": "crew"}
    )
    team_id = team.json()["data"]["id"]
    member_id = uuid4()
    async with tenant_transaction(api, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.members (id, organization_id, email, status, idp_subject, display_name) "
            "VALUES ($1, $2, $3, 'active', $4, 'New Member')",
            member_id,
            org_id,
            f"member-{member_id.hex[:8]}@example.test",
            f"sub-{member_id}",
        )
    added = await client.post(
        f"/api/v1/teams/{team_id}/members",
        headers=headers,
        json={"member_id": str(member_id), "team_role": "member"},
    )
    assert added.status_code == 201

    for _ in range(10):  # a hard cap: a stuck test must fail, not hang
        if await run_dispatcher(worker, default_registry(), "e2e-worker", OPTIONS) == 0:
            break

    received: list[httpx.Request] = []

    def receiver(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(204)

    async def resolve(name: str, port: int) -> list[str]:
        return ["93.184.216.34"]

    def egress(hosts: list[str], private: bool) -> EgressClient:
        return EgressClient(hosts, resolver=resolve, transport=httpx.MockTransport(receiver))

    registry = ChannelRegistry()
    registry.register(WebhookChannel)
    sender = SenderDeps(
        registry,
        ChannelRuntime(ChannelCredentialStore(secrets_provider), egress_factory=egress),
        CircuitRegistry(),
    )
    assert (
        await run_sender(worker, sender, "e2e-sender") == 1
    )  # only team_member.added; team.created is not listed

    assert len(received) == 1
    request = received[0]
    body = request.content
    sent_at = int(request.headers["x-assetflow-timestamp"])
    assert abs(int(datetime.now(UTC).timestamp()) - sent_at) <= 300  # inside the receiver's 5-minute window
    expected = hmac.new(SECRET.encode(), str(sent_at).encode() + b"." + body, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(request.headers["x-assetflow-signature"], f"sha256={expected}")

    payload = json.loads(body)
    assert payload["event_type"] == "team_member.added"
    assert payload["organization_id"] == str(org_id)
    assert payload["member"] == str(member_id)
    assert payload["team"] == {"id": team_id, "role": "member"}
    assert datetime.fromisoformat(payload["occurred_at"]).tzinfo is not None
    assert set(payload) == {"event_type", "event_id", "occurred_at", "organization_id", "member", "team"}

    delivery = await admin_db.fetchrow(
        "SELECT status, target, idempotency_key, error_code FROM public.notification_deliveries "
        "WHERE channel_key = 'webhook'"
    )
    assert delivery is not None
    assert (delivery["status"], delivery["error_code"]) == ("sent", None)
    assert request.headers["x-assetflow-delivery-id"] == delivery["idempotency_key"]
    assert delivery["target"] == str(member_id)
    assert (
        await admin_db.fetchval(
            "SELECT count(*) FROM public.notification_deliveries WHERE channel_key = 'webhook'"
        )
        == 1
    )
