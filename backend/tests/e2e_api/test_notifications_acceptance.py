# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""M1.5 acceptance (§C8.6 "Notifications"): one event reaches three channels; a failing relay dead-letters.

The real app, outbox dispatcher, automation subscriber and notification sender run against real
PostgreSQL. In the first test the email goes over SMTP to the Mailpit container of the minimal stack
(skipped when it is not reachable) and the webhook to a recorded receiver. In the second, the relay
is a closed port and the test clock walks through the retries (1 s, then 4 s) to the dead letter.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import socket
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx
import pytest
import time_machine
from pg_harness import IsolationDb, PoolFactory

from app.channels.circuit import CircuitRegistry
from app.channels.credentials import ChannelCredentialStore
from app.channels.egress import EgressClient, system_resolver
from app.channels.email import EmailChannel
from app.channels.inapp import InAppChannel
from app.channels.registry import ChannelRegistry
from app.channels.runtime import ChannelRuntime
from app.channels.webhook import WebhookChannel
from app.core.config import EmailChannelConfig
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

CHANNELS = "/api/v1/notification-channels"
HOOK_HOST = "hooks.example.test"
SECRET = "whsec-acceptance-throwaway-secret"
SMTP_PORT = int(os.environ.get("ASSETFLOW_TEST_MAILPIT_SMTP_PORT", "11025"))
MAILPIT_API = os.environ.get("ASSETFLOW_TEST_MAILPIT_API", "http://127.0.0.1:18025")
OPTIONS = DispatcherOptions(batch_size=50, reclaim_after_seconds=300, max_attempts=3)
NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
#: A closed port is refused at once on Linux and times out on Windows; both are retryable.
UNREACHABLE = {"connection_error", "timeout"}
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
    "        - webhook\n"
    "      template: team-member-added\n"
)


def _mailpit_up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", SMTP_PORT), timeout=1) as sock:
            sock.settimeout(1.0)
            banner = sock.recv(64)
            return b"220" in banner
    except (OSError, TimeoutError):
        return False


def _closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


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
    for channel in (InAppChannel, EmailChannel, WebhookChannel):
        channels.register(channel)
    app.state.channel_registry = channels
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def admin_db(isolation_db: IsolationDb) -> AsyncIterator[asyncpg.Connection[asyncpg.Record]]:
    conn = await asyncpg.connect(isolation_db.admin_dsn)
    yield conn
    for table in ("notification_deliveries", "notifications", "notification_channels"):
        await conn.execute(f"DELETE FROM public.{table}")  # noqa: S608 - fixed table names
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


def _as(org_id: UUID, member_id: UUID, role: str = "admin") -> dict[str, str]:
    return {
        "x-organization-id": str(org_id),
        "x-member-id": str(member_id),
        "x-role": role,
        "x-scope-type": "organization",
    }


async def _install_channels(client: httpx.AsyncClient, admin: dict[str, str], *, webhook: bool) -> None:
    email = await client.post(
        f"{CHANNELS}/installations",
        headers=admin,
        json={"channel_key": "email", "settings": {"from_address": "alerts@assetflow.test"}},
    )
    assert email.status_code == 201, email.text
    if webhook:
        hook = await client.post(
            f"{CHANNELS}/installations",
            headers=admin,
            json={
                "channel_key": "webhook",
                "settings": {
                    "url": f"https://{HOOK_HOST}/inbound",
                    "events": ["team_member.added"],
                    "field_mapping": {"team.id": "team_id", "team.role": "team_role", "member": "member_id"},
                },
                "secrets": {"signing_secret": SECRET},
            },
        )
        assert hook.status_code == 201, hook.text


async def _new_member(pool: Pool, org_id: UUID) -> tuple[UUID, str]:
    member_id, address = uuid4(), f"member-{uuid4().hex[:10]}@example.test"
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.members (id, organization_id, email, status, idp_subject, display_name) "
            "VALUES ($1, $2, $3, 'active', $4, 'New Member')",
            member_id,
            org_id,
            address,
            f"sub-{member_id}",
        )
    return member_id, address


async def _add_to_team(client: httpx.AsyncClient, admin: dict[str, str], member_id: UUID, code: str) -> str:
    team = await client.post(
        "/api/v1/teams", headers=admin, json={"code": code, "name": code.title(), "type": "crew"}
    )
    team_id = str(team.json()["data"]["id"])
    added = await client.post(
        f"/api/v1/teams/{team_id}/members",
        headers=admin,
        json={"member_id": str(member_id), "team_role": "member"},
    )
    assert added.status_code == 201, added.text
    return team_id


async def _drain(worker: Pool) -> None:
    for _ in range(10):  # a hard cap: a stuck test must fail, not hang
        if await run_dispatcher(worker, default_registry(), "acceptance-worker", OPTIONS) == 0:
            return
    raise AssertionError("outbox did not drain")


def _sender(
    secrets: FileSecretsProvider, receiver: list[httpx.Request], smtp_port: int, *, timeout: float = 2.0
) -> SenderDeps:
    async def resolve(name: str, port: int) -> list[str]:
        return ["93.184.216.34"] if name == HOOK_HOST else await system_resolver(name, port)

    def record(request: httpx.Request) -> httpx.Response:
        receiver.append(request)
        return httpx.Response(204)

    def egress(hosts: list[str], private: bool) -> EgressClient:
        return EgressClient(
            hosts, resolver=resolve, transport=httpx.MockTransport(record), allow_private_addresses=private
        )

    registry = ChannelRegistry()
    registry.register(EmailChannel)
    registry.register(WebhookChannel)
    email = EmailChannelConfig(
        enabled=True,
        host="127.0.0.1",
        port=smtp_port,
        security="none",
        default_from="noreply@assetflow.test",
        timeout_seconds=timeout,
        allow_private_addresses=True,
    )
    return SenderDeps(
        registry,
        ChannelRuntime(ChannelCredentialStore(secrets), egress_factory=egress),
        CircuitRegistry(),
        platform={"email": email.model_dump()},
    )


async def _find_mail(address: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10) as http:
        for _ in range(20):
            found = (await http.get(f"{MAILPIT_API}/api/v1/search", params={"query": f"to:{address}"})).json()
            if found.get("messages"):
                message = (
                    await http.get(f"{MAILPIT_API}/api/v1/message/{found['messages'][0]['ID']}")
                ).json()
                await http.request("DELETE", f"{MAILPIT_API}/api/v1/messages", json={"IDs": [message["ID"]]})
                return message  # type: ignore[no-any-return]
            await asyncio.sleep(0.25)
    raise AssertionError(f"no mail for {address} reached Mailpit")


@pytest.mark.skipif(not _mailpit_up(), reason="Mailpit is not reachable (make up-minimal)")
async def test_one_event_reaches_the_inbox_mailpit_and_a_signed_webhook_and_is_logged(
    client: httpx.AsyncClient, make_pool: PoolFactory, secrets_provider: FileSecretsProvider
) -> None:
    api, worker = await make_pool("api"), await make_pool("worker")
    org, admin_id = await _org_with_admin(api)
    admin = _as(org, admin_id)
    await _install_channels(client, admin, webhook=True)
    member_id, address = await _new_member(api, org)
    team_id = await _add_to_team(client, admin, member_id, "crew-1")
    await _drain(worker)

    received: list[httpx.Request] = []
    assert await run_sender(worker, _sender(secrets_provider, received, SMTP_PORT), "acceptance-sender") == 2

    inbox = (await client.get("/api/v1/notifications", headers=_as(org, member_id, "member"))).json()["data"][
        "items"
    ]
    assert len(inbox) == 1

    mail = await _find_mail(address)
    assert mail["From"]["Address"] == "alerts@assetflow.test"
    assert mail["Subject"] == "You were added to a team"
    assert "member" in mail["Text"]

    assert len(received) == 1
    request = received[0]
    stamp = request.headers["x-assetflow-timestamp"]
    expected = hmac.new(SECRET.encode(), stamp.encode() + b"." + request.content, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(request.headers["x-assetflow-signature"], f"sha256={expected}")
    payload = json.loads(request.content)
    assert payload["team"] == {"id": team_id, "role": "member"}
    assert payload["member"] == str(member_id)
    assert payload["organization_id"] == str(org)

    log = (await client.get(f"{CHANNELS}/deliveries", headers=admin)).json()["data"]["items"]
    mine = {row["channel_key"]: row for row in log if row["recipient_member_id"] == str(member_id)}
    assert set(mine) == {"inapp", "email", "webhook"}
    assert {row["status"] for row in mine.values()} == {"sent"}
    assert all(row["latency_ms"] is not None for row in mine.values())
    assert all(row["target"] == str(member_id) for row in mine.values())  # never an address
    assert address not in json.dumps(log)


async def test_a_failing_relay_retries_then_dead_letters_and_tells_the_admins(
    client: httpx.AsyncClient,
    make_pool: PoolFactory,
    secrets_provider: FileSecretsProvider,
    admin_db: asyncpg.Connection[asyncpg.Record],
) -> None:
    api, worker = await make_pool("api"), await make_pool("worker")
    org, admin_id = await _org_with_admin(api)
    admin = _as(org, admin_id)
    await _install_channels(client, admin, webhook=False)
    member_id, _ = await _new_member(api, org)
    await _add_to_team(client, admin, member_id, "crew-2")
    await _drain(worker)
    deps = _sender(secrets_provider, [], _closed_port(), timeout=0.5)

    async def delivery() -> asyncpg.Record:
        row = await admin_db.fetchrow(
            "SELECT * FROM public.notification_deliveries "
            "WHERE channel_key = 'email' AND organization_id = $1",
            org,
        )
        assert row is not None
        return row

    with time_machine.travel(NOW, tick=False) as clock:
        await run_sender(worker, deps, "acceptance-sender")
        first = await delivery()
        assert (first["status"], first["attempts"]) == ("failed", 1)
        assert first["error_code"] in UNREACHABLE
        assert first["next_retry_at"] == NOW + timedelta(seconds=1)

        clock.shift(timedelta(seconds=2))
        await run_sender(worker, deps, "acceptance-sender")
        second = await delivery()
        assert (second["status"], second["attempts"]) == ("failed", 2)
        assert second["next_retry_at"] == NOW + timedelta(seconds=2 + 4)

        clock.shift(timedelta(seconds=5))
        await run_sender(worker, deps, "acceptance-sender")
    last = await delivery()
    assert (last["status"], last["attempts"]) == ("dead_lettered", 3)
    assert last["error_code"] in UNREACHABLE

    alerts = (await client.get("/api/v1/notifications", headers=admin)).json()["data"]["items"]
    assert [a["title_key"] for a in alerts if "could not be delivered" in a["title_key"]] == [
        "A notification could not be delivered"
    ]
    audit = await admin_db.fetchrow(
        "SELECT entity_type, entity_id, after_state FROM public.audit_events "
        "WHERE action = $1 AND organization_id = $2",
        "notification_delivery.dead_lettered",
        org,
    )
    assert audit is not None
    assert audit["entity_id"] == last["entity_id"]  # the note is on the record the event was about
    assert audit["entity_type"] == last["entity_type"]

    log = (await client.get(f"{CHANNELS}/deliveries?status=dead_lettered", headers=admin)).json()["data"][
        "items"
    ]
    assert [(row["channel_key"], row["attempts"], row["error_code"]) for row in log] == [
        ("email", 3, last["error_code"])
    ]
    assert last["error_code"] in UNREACHABLE
