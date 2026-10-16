# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Email through the real sender and PostgreSQL, with a local SMTP server (§B6.3, M1.5-T4).

A pending email delivery is picked up by the sender, the member's address is read from the member
record at send time, the mail reaches the server, and the delivery log keeps only the member id.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import pytest
import time_machine
from fake_smtp import SERVER_NAME, FakeSmtp, Script, run_server
from pg_harness import IsolationDb, PoolFactory
from tenant_checks import token

from app.channels.base import NotificationChannel
from app.channels.circuit import CircuitRegistry
from app.channels.credentials import ChannelCredentialStore
from app.channels.egress import EgressClient
from app.channels.email import EmailChannel
from app.channels.registry import ChannelRegistry
from app.channels.runtime import ChannelRuntime
from app.core.config import EmailChannelConfig
from app.core.db import tenant_transaction
from app.engines.automation.planner import NotificationIntent
from app.modules.notifications import rendering
from app.modules.notifications.dispatch import enqueue
from app.providers.context import ProviderContext
from app.providers.secrets.file import FileSecretsProvider
from workers.notification_sender import SenderDeps, run_once

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
DEFAULT_SETTINGS = {"from_address": "alerts@org.example.test", "from_name": "Org Alerts"}


class _TrustingRegistry(ChannelRegistry):
    """Builds `email` with a TLS context that trusts the test server's CA."""

    def __init__(self, server: FakeSmtp) -> None:
        super().__init__()
        self._trusting = server.certificates.trusting_client_context

    def get(self, key: str) -> type[NotificationChannel] | None:
        if key != "email":
            return None
        trusting = self._trusting

        class Trusting(EmailChannel):
            def __init__(self) -> None:
                super().__init__(tls_context=trusting)

        return Trusting


class Rig:
    def __init__(self, admin: asyncpg.Connection[asyncpg.Record], org: uuid.UUID, tmp_path: Path) -> None:
        self.admin, self.org, self.tmp_path = admin, org, tmp_path
        self.address = f"{token()}@members.example.test"

    async def member(self, *, status: str = "active") -> uuid.UUID:
        member_id = uuid.uuid4()
        await self.admin.execute(
            "INSERT INTO public.members (id, organization_id, idp_subject, email, display_name, status) "
            "VALUES ($1, $2, $3, $4, 'Ada Lovelace', $5)",
            member_id,
            self.org,
            f"idp-{token()}",
            self.address,
            status,
        )
        return member_id

    async def install(self, *, allow_personal: bool = False) -> uuid.UUID:
        channel_id = uuid.uuid4()
        await self.admin.execute(
            "INSERT INTO public.notification_channels (id, organization_id, channel_key, display_name, "
            "settings, allow_personal_data) VALUES ($1, $2, 'email', 'Email', $3::jsonb, $4)",
            channel_id,
            self.org,
            json.dumps(DEFAULT_SETTINGS),
            allow_personal,
        )
        return channel_id

    async def delivery(self, channel_id: uuid.UUID, member_id: uuid.UUID) -> uuid.UUID:
        delivery_id = uuid.uuid4()
        await self.admin.execute(
            "INSERT INTO public.notification_deliveries (id, organization_id, channel_id, channel_key, "
            "event_id, recipient_member_id, target, idempotency_key, status, template_key, event_type, "
            "message_data) VALUES ($1, $2, $3, 'email', $4, $5, $6, $7, 'pending', 'team-member-added', "
            "'team_member.added', $8::jsonb)",
            delivery_id,
            self.org,
            channel_id,
            uuid.uuid4(),
            member_id,
            str(member_id),
            f"{delivery_id.hex}{delivery_id.hex}",
            json.dumps({"team_id": "t", "member_id": "m", "team_role": "lead"}),
        )
        return delivery_id

    def deps(self, server: FakeSmtp, *, allow_private: bool = True) -> SenderDeps:
        registry = _TrustingRegistry(server)
        context = ProviderContext(env="test", pillar="secrets", base_dir=self.tmp_path)
        provider = FileSecretsProvider.from_settings({"directory": "secrets"}, context)
        platform = EmailChannelConfig(
            enabled=True,
            host=SERVER_NAME,
            port=server.port,
            security="starttls",
            default_from="noreply@platform.example.test",
            timeout_seconds=2.0,
            allow_private_addresses=allow_private,
        ).model_dump()

        async def resolve(name: str, port: int) -> list[str]:
            return ["127.0.0.1"]

        def egress(hosts: list[str], private: bool) -> EgressClient:
            return EgressClient(hosts, resolver=resolve, allow_private_addresses=private)

        runtime = ChannelRuntime(ChannelCredentialStore(provider), egress_factory=egress)
        return SenderDeps(registry, runtime, CircuitRegistry(), platform={"email": platform})

    async def row(self, delivery_id: uuid.UUID) -> asyncpg.Record:
        row = await self.admin.fetchrow(
            "SELECT * FROM public.notification_deliveries WHERE id = $1", delivery_id
        )
        assert row is not None
        return row


@pytest.fixture
async def rig(isolation_db: IsolationDb, tmp_path: Path) -> AsyncIterator[Rig]:
    admin = await asyncpg.connect(isolation_db.admin_dsn)
    await _clean(admin)
    yield Rig(admin, isolation_db.org_a, tmp_path)
    await _clean(admin)
    await admin.close()


async def _clean(conn: asyncpg.Connection[asyncpg.Record]) -> None:
    await conn.execute("DELETE FROM public.notification_deliveries")
    await conn.execute("DELETE FROM public.notification_channels")
    await conn.execute("DELETE FROM public.notifications")
    await conn.execute("DELETE FROM public.outbox WHERE event_type LIKE 'notification_delivery.%'")


async def test_a_pending_email_is_sent_and_the_log_keeps_only_the_member_id(
    make_pool: PoolFactory, rig: Rig
) -> None:
    channel, member = await rig.install(), await rig.member()
    delivery = await rig.delivery(channel, member)
    async with run_server() as server:
        with time_machine.travel(NOW, tick=False):
            await run_once(await make_pool("worker"), rig.deps(server), "sender-1")
        assert server.received.recipients == [rig.address]
        assert server.received.senders == ["alerts@org.example.test"]
        assert server.received.tls_sessions == 1
    row = await rig.row(delivery)
    assert (row["status"], row["attempts"], row["error_code"]) == ("sent", 1, None)
    assert row["target"] == str(member)
    assert rig.address not in json.dumps({k: str(v) for k, v in dict(row).items()})


async def test_a_member_who_has_left_is_skipped_without_an_alert(make_pool: PoolFactory, rig: Rig) -> None:
    channel, member = await rig.install(), await rig.member(status="left")
    delivery = await rig.delivery(channel, member)
    async with run_server() as server:
        with time_machine.travel(NOW, tick=False):
            await run_once(await make_pool("worker"), rig.deps(server), "sender-1")
        assert server.received.connections == 0
    row = await rig.row(delivery)
    assert (row["status"], row["error_code"], row["attempts"]) == ("skipped", "recipient.unavailable", 0)
    assert await rig.admin.fetchval("SELECT count(*) FROM public.notifications") == 0


async def test_a_permanent_smtp_refusal_dead_letters_at_once(make_pool: PoolFactory, rig: Rig) -> None:
    channel, member = await rig.install(), await rig.member()
    delivery = await rig.delivery(channel, member)
    async with run_server(script=Script(replies={"RCPT": "550 no such user"})) as server:
        with time_machine.travel(NOW, tick=False):
            await run_once(await make_pool("worker"), rig.deps(server), "sender-1")
    row = await rig.row(delivery)
    assert (row["status"], row["error_code"], row["attempts"]) == ("dead_lettered", "smtp_550", 1)


async def test_a_transient_smtp_refusal_is_retried(make_pool: PoolFactory, rig: Rig) -> None:
    channel, member = await rig.install(), await rig.member()
    delivery = await rig.delivery(channel, member)
    async with run_server(script=Script(replies={"RCPT": "450 try later"})) as server:
        with time_machine.travel(NOW, tick=False):
            await run_once(await make_pool("worker"), rig.deps(server), "sender-1")
    row = await rig.row(delivery)
    assert (row["status"], row["error_code"], row["attempts"]) == ("failed", "smtp_450", 1)
    assert row["next_retry_at"] is not None


async def test_a_private_relay_address_is_refused_unless_the_platform_allows_it(
    make_pool: PoolFactory, rig: Rig
) -> None:
    channel, member = await rig.install(), await rig.member()
    delivery = await rig.delivery(channel, member)
    async with run_server() as server:
        with time_machine.travel(NOW, tick=False):
            await run_once(await make_pool("worker"), rig.deps(server, allow_private=False), "sender-1")
        assert server.received.connections == 0
    assert (await rig.row(delivery))["error_code"] == "channel.egress_denied"


async def test_personal_fields_are_stored_only_when_the_installation_allows_them(
    make_pool: PoolFactory, rig: Rig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    templates = tmp_path / "templates" / "en"
    templates.mkdir(parents=True)
    front = "---\nfields: [team_role, display_name]\npersonal_fields: [display_name]\n---\n"
    (templates / "personal-note.txt").write_text(
        front + "{{ display_name }} is {{ team_role }}\n", encoding="utf-8"
    )
    monkeypatch.setattr(rendering, "TEMPLATES_DIR", templates)
    member = await rig.member()
    worker = await make_pool("worker")

    async def queued(*, allow: bool) -> dict[str, str]:
        await rig.admin.execute("DELETE FROM public.notification_deliveries")
        await rig.admin.execute("DELETE FROM public.notification_channels")
        await rig.install(allow_personal=allow)
        intent = NotificationIntent(
            event_id=uuid.uuid4(),
            organization_id=rig.org,
            member_id=member,
            channel_key="email",
            template_key="personal-note",
            idempotency_key=uuid.uuid4().hex * 2,
            event_type="team_member.added",
            event_data={"team_role": "lead", "display_name": "Ada Lovelace", "other": "dropped"},
        )
        async with tenant_transaction(worker, rig.org) as conn:
            await enqueue(conn, [intent])
        stored = await rig.admin.fetchval("SELECT message_data FROM public.notification_deliveries")
        return json.loads(stored)  # type: ignore[no-any-return]

    assert await queued(allow=False) == {"team_role": "lead"}
    assert await queued(allow=True) == {"display_name": "Ada Lovelace", "team_role": "lead"}
