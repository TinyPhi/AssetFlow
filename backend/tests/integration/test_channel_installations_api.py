# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Channel administration and the sender together, against a real PostgreSQL (§B6.3 rule 6, M1.5-T6).

The kill switch and re-queue are done through the admin service as the `api` role (so its grants
are exercised) and then observed through the real sender running as the `worker` role.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

import asyncpg
import pytest
import time_machine
from pg_harness import IsolationDb, PoolFactory
from pydantic import BaseModel
from tenant_checks import token

from app.channels.base import ChannelContext, DeliveryResult, NotificationChannel, RenderedMessage
from app.channels.circuit import CircuitRegistry
from app.channels.credentials import ChannelCredentialStore
from app.channels.registry import ChannelRegistry
from app.channels.retry import failure_from_status
from app.channels.runtime import ChannelRuntime
from app.core.db import Pool, tenant_transaction
from app.modules.notifications import channels_service
from app.modules.notifications.channel_schemas import InstallationCreate
from app.providers.context import ProviderContext
from app.providers.secrets.file import FileSecretsProvider
from workers.notification_sender import SenderDeps, run_once

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


class _Settings(BaseModel):
    pass


class _Calls:
    def __init__(self) -> None:
        self.keys: list[str] = []
        self.outcome: DeliveryResult = DeliveryResult(delivered=True)


def _channel(calls: _Calls) -> type[NotificationChannel]:
    class Scripted(NotificationChannel):
        key: ClassVar[str] = "scripted"
        config_schema: ClassVar[type[BaseModel]] = _Settings

        async def send(
            self, ctx: ChannelContext, target: str, message: RenderedMessage, idempotency_key: str
        ) -> DeliveryResult:
            calls.keys.append(idempotency_key)
            return calls.outcome

        async def health(self, ctx: ChannelContext) -> dict[str, Any]:
            return {"healthy": True}

    return Scripted


class Rig:
    def __init__(self, admin: asyncpg.Connection[asyncpg.Record], tmp_path: Path, org: uuid.UUID) -> None:
        self.admin, self.org, self.calls = admin, org, _Calls()
        self.registry = ChannelRegistry()
        self.registry.register(_channel(self.calls))
        context = ProviderContext(env="test", pillar="secrets", base_dir=tmp_path)
        self.store = ChannelCredentialStore(
            FileSecretsProvider.from_settings({"directory": "secrets"}, context)
        )
        self.member: uuid.UUID | None = None

    def deps(self) -> SenderDeps:
        return SenderDeps(self.registry, ChannelRuntime(self.store), CircuitRegistry())

    async def install(self, api: Pool) -> uuid.UUID:
        async with tenant_transaction(api, self.org) as conn:
            installed = await channels_service.install(
                conn,
                store=self.store,
                registry=self.registry,
                organization_id=self.org,
                actor_member_id=None,
                data=InstallationCreate(channel_key="scripted"),
            )
        return installed.id

    async def delivery(
        self, channel_id: uuid.UUID, *, status: str = "pending", attempts: int = 0
    ) -> uuid.UUID:
        if self.member is None:
            self.member = uuid.uuid4()
            await self.admin.execute(
                "INSERT INTO public.members (id, organization_id, idp_subject, email, display_name, status) "
                "VALUES ($1, $2, $3, $4, 'Test Member', 'active')",
                self.member,
                self.org,
                f"idp-{token()}",
                f"{token()}@example.org",
            )
        delivery_id = uuid.uuid4()
        await self.admin.execute(
            "INSERT INTO public.notification_deliveries "
            "(id, organization_id, channel_id, channel_key, event_id, "
            "recipient_member_id, target, idempotency_key, status, attempts, template_key, event_type, "
            "message_data) VALUES ($1, $2, $3, 'scripted', $4, $5, $6, $7, $8, $9, 'team-member-added', "
            "'team_member.added', $10::jsonb)",
            delivery_id,
            self.org,
            channel_id,
            uuid.uuid4(),
            self.member,
            str(self.member),
            f"key-{delivery_id}",
            status,
            attempts,
            '{"team_id": "t", "member_id": "m", "team_role": "member"}',
        )
        return delivery_id

    async def status(self, delivery_id: uuid.UUID) -> tuple[str, int, str | None]:
        row = await self.admin.fetchrow(
            "SELECT status, attempts, error_code FROM public.notification_deliveries WHERE id = $1",
            delivery_id,
        )
        assert row is not None
        return row["status"], row["attempts"], row["error_code"]


@pytest.fixture
async def rig(isolation_db: IsolationDb, tmp_path: Path) -> AsyncIterator[Rig]:
    admin = await asyncpg.connect(isolation_db.admin_dsn)
    await _clean(admin)
    yield Rig(admin, tmp_path, isolation_db.org_a)
    await _clean(admin)
    await admin.close()


async def _clean(conn: asyncpg.Connection[asyncpg.Record]) -> None:
    await conn.execute("DELETE FROM public.notification_deliveries")
    await conn.execute("DELETE FROM public.notification_channels")
    await conn.execute("DELETE FROM public.notifications")
    await conn.execute(
        "DELETE FROM public.outbox WHERE event_type LIKE 'notification_channel.%' "
        "OR event_type LIKE 'notification_delivery.%'"
    )


async def test_the_kill_switch_stops_sending_at_the_next_claim_and_enable_resumes(
    make_pool: PoolFactory, rig: Rig
) -> None:
    api, worker = await make_pool("api"), await make_pool("worker")
    channel_id = await rig.install(api)
    held = await rig.delivery(channel_id)

    async with tenant_transaction(api, rig.org) as conn:
        off = await channels_service.set_enabled(
            conn,
            registry=rig.registry,
            organization_id=rig.org,
            actor_member_id=None,
            installation_id=channel_id,
            enabled=False,
        )
    assert off.enabled is False
    with time_machine.travel(NOW, tick=False):
        await run_once(worker, rig.deps(), "sender-1")
    assert await rig.status(held) == ("skipped", 0, "channel.disabled")
    assert rig.calls.keys == []
    assert (
        await rig.admin.fetchval(
            "SELECT count(*) FROM public.notification_channels WHERE id = $1", channel_id
        )
        == 1
    )

    async with tenant_transaction(api, rig.org) as conn:
        await channels_service.set_enabled(
            conn,
            registry=rig.registry,
            organization_id=rig.org,
            actor_member_id=None,
            installation_id=channel_id,
            enabled=True,
        )
    fresh = await rig.delivery(channel_id)
    with time_machine.travel(NOW, tick=False):
        await run_once(worker, rig.deps(), "sender-1")
    assert await rig.status(fresh) == ("sent", 1, None)
    assert rig.calls.keys == [f"key-{fresh}"]
    assert (await rig.status(held))[0] == "skipped"  # a skipped delivery is not resurrected by enabling


async def test_a_requeued_dead_letter_is_delivered(make_pool: PoolFactory, rig: Rig) -> None:
    api, worker = await make_pool("api"), await make_pool("worker")
    channel_id = await rig.install(api)
    delivery = await rig.delivery(channel_id)
    rig.calls.outcome = failure_from_status(404)  # a 4xx: dead-lettered on the first attempt

    with time_machine.travel(NOW, tick=False):
        await run_once(worker, rig.deps(), "sender-1")
    assert await rig.status(delivery) == ("dead_lettered", 1, "http_404")

    async with tenant_transaction(api, rig.org) as conn:
        row = await channels_service.requeue_dead_letter(
            conn, organization_id=rig.org, actor_member_id=None, delivery_id=delivery
        )
    assert (row["status"], row["attempts"]) == ("pending", 0)

    rig.calls.outcome = DeliveryResult(delivered=True)
    with time_machine.travel(NOW + timedelta(seconds=5), tick=False):
        await run_once(worker, rig.deps(), "sender-1")
    assert await rig.status(delivery) == ("sent", 1, None)
    assert rig.calls.keys == [f"key-{delivery}", f"key-{delivery}"]  # same idempotency key both times


async def test_the_api_role_can_requeue_but_not_rewrite_a_delivery(make_pool: PoolFactory, rig: Rig) -> None:
    api = await make_pool("api")
    channel_id = await rig.install(api)
    delivery = await rig.delivery(channel_id, status="dead_lettered", attempts=3)
    statements = (
        "UPDATE public.notification_deliveries SET target = target WHERE id = $1",
        "UPDATE public.notification_deliveries SET idempotency_key = idempotency_key WHERE id = $1",
        "UPDATE public.notification_deliveries SET recipient_member_id = recipient_member_id WHERE id = $1",
        "UPDATE public.notification_deliveries SET template_key = template_key WHERE id = $1",
    )
    async with tenant_transaction(api, rig.org) as conn:
        for statement in statements:
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                async with conn.transaction():
                    await conn.execute(statement, delivery)
