# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""E2E: an organization event becomes an email in Mailpit (§B6.3, §C8.6, M1.5-T4).

The real app, outbox dispatcher, automation subscriber and notification sender run against real
PostgreSQL, and the mail goes over SMTP to the Mailpit container of the minimal stack (`make
up-minimal`: SMTP on host port 11025, API on 18025; override with ASSETFLOW_TEST_MAILPIT_SMTP_PORT
and ASSETFLOW_TEST_MAILPIT_API). Skipped when Mailpit is not reachable.
"""

from __future__ import annotations

import asyncio
import os
import socket
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from pg_harness import PoolFactory

from app.channels.circuit import CircuitRegistry
from app.channels.credentials import ChannelCredentialStore
from app.channels.email import EmailChannel
from app.channels.inapp import InAppChannel
from app.channels.registry import ChannelRegistry
from app.channels.runtime import ChannelRuntime
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

SMTP_PORT = int(os.environ.get("ASSETFLOW_TEST_MAILPIT_SMTP_PORT", "11025"))
MAILPIT_API = os.environ.get("ASSETFLOW_TEST_MAILPIT_API", "http://127.0.0.1:18025")
OPTIONS = DispatcherOptions(batch_size=50, reclaim_after_seconds=300, max_attempts=3)
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
)


def _mailpit_up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", SMTP_PORT), timeout=1):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _mailpit_up(), reason="Mailpit is not reachable (make up-minimal)")


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
    channels.register(EmailChannel)
    app.state.channel_registry = channels
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


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


async def _find_mail(http: httpx.AsyncClient, address: str) -> dict[str, Any]:
    for _ in range(20):
        found = (await http.get(f"{MAILPIT_API}/api/v1/search", params={"query": f"to:{address}"})).json()
        if found.get("messages"):
            summary = found["messages"][0]
            return (await http.get(f"{MAILPIT_API}/api/v1/message/{summary['ID']}")).json()  # type: ignore[no-any-return]
        await asyncio.sleep(0.25)
    raise AssertionError(f"no mail for {address} reached Mailpit")


async def test_adding_a_team_member_sends_an_email_that_reaches_mailpit(
    client: httpx.AsyncClient,
    make_pool: PoolFactory,
    secrets_provider: FileSecretsProvider,
) -> None:
    api, worker = await make_pool("api"), await make_pool("worker")
    org_id, admin_id = await _org_with_admin(api)
    headers = _as_admin(org_id, admin_id)

    installed = await client.post(
        "/api/v1/notification-channels/installations",
        headers=headers,
        json={
            "channel_key": "email",
            "settings": {"from_address": "alerts@assetflow.test", "from_name": "AssetFlow Alerts"},
        },
    )
    assert installed.status_code == 201, installed.text

    team = await client.post(
        "/api/v1/teams", headers=headers, json={"code": "crew-1", "name": "Crew One", "type": "crew"}
    )
    team_id = team.json()["data"]["id"]
    member_id, address = uuid4(), f"member-{uuid4().hex[:10]}@example.test"
    async with tenant_transaction(api, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.members (id, organization_id, email, status, idp_subject, display_name) "
            "VALUES ($1, $2, $3, 'active', $4, 'New Member')",
            member_id,
            org_id,
            address,
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
    sender = SenderDeps(
        _registry_with_email(),
        ChannelRuntime(ChannelCredentialStore(secrets_provider)),
        CircuitRegistry(),
        platform={
            "email": EmailChannelConfig(
                enabled=True,
                host="localhost",
                port=SMTP_PORT,
                security="none",
                default_from="noreply@assetflow.test",
                allow_private_addresses=True,
            ).model_dump()
        },
    )
    assert await run_sender(worker, sender, "e2e-sender") >= 1

    async with tenant_transaction(api, org_id) as conn:
        delivery = await conn.fetchrow(
            "SELECT status, target, idempotency_key, error_code FROM public.notification_deliveries "
            "WHERE channel_key = 'email'"
        )
    assert delivery is not None
    assert (delivery["status"], delivery["error_code"]) == ("sent", None)
    assert delivery["target"] == str(member_id)  # the log never holds the address

    async with httpx.AsyncClient(timeout=10) as http:
        mail = await _find_mail(http, address)
        try:
            assert mail["From"]["Address"] == "alerts@assetflow.test"
            assert mail["From"]["Name"] == "AssetFlow Alerts"
            assert [t["Address"] for t in mail["To"]] == [address]
            assert mail["Subject"] == "You were added to a team"
            assert "member" in mail["Text"]
            assert "<strong>member</strong>" in mail["HTML"]
            assert mail["MessageID"] == f"{delivery['idempotency_key']}@assetflow.test"
        finally:
            await http.request("DELETE", f"{MAILPIT_API}/api/v1/messages", json={"IDs": [mail["ID"]]})


def _registry_with_email() -> ChannelRegistry:
    registry = ChannelRegistry()
    registry.register(EmailChannel)
    return registry
