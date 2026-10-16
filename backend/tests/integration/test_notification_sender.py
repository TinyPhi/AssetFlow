# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The notification sender against a real PostgreSQL (§B6.3 rules 4-8, §B6.1 rule 9, M1.5-T6)."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
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
from app.core.db import Pool
from app.providers.context import ProviderContext
from app.providers.secrets.file import FileSecretsProvider
from workers.notification_sender import SenderDeps, SenderOptions, run_once

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
FROZEN = "2026-03-01T12:00:00Z"


class _Settings(BaseModel):
    pass


@dataclass
class Script:
    """What a stand-in channel does: its outcomes in order (the last repeats), and what it was asked."""

    outcomes: list[DeliveryResult | Exception] = field(default_factory=list)
    calls: list[tuple[str, str, str]] = field(default_factory=list)  # (organization, target, key)
    delay: float = 0.0


def _channel_class(script: Script) -> type[NotificationChannel]:
    class Scripted(NotificationChannel):
        key: ClassVar[str] = "scripted"
        config_schema: ClassVar[type[BaseModel]] = _Settings

        async def send(
            self, ctx: ChannelContext, target: str, message: RenderedMessage, idempotency_key: str
        ) -> DeliveryResult:
            script.calls.append((ctx.organization_id, target, idempotency_key))
            if script.delay:
                await asyncio.sleep(script.delay)
            index = min(len(script.calls) - 1, len(script.outcomes) - 1)
            outcome = script.outcomes[index] if script.outcomes else DeliveryResult(delivered=True)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        async def health(self, ctx: ChannelContext) -> dict[str, Any]:
            return {"healthy": True}

    return Scripted


class World:
    """Seeds organizations through the superuser connection and removes what it seeded."""

    def __init__(self, admin: asyncpg.Connection[asyncpg.Record], tmp_path: Path) -> None:
        self.admin = admin
        self.tmp_path = tmp_path
        self.members: list[uuid.UUID] = []
        self.channels: list[uuid.UUID] = []
        self.event_ids: list[uuid.UUID] = []

    async def member(self, organization_id: uuid.UUID, *, admin_role: bool = False) -> uuid.UUID:
        member_id = uuid.uuid4()
        await self.admin.execute(
            "INSERT INTO public.members (id, organization_id, idp_subject, email, display_name, status) "
            "VALUES ($1, $2, $3, $4, 'Test Member', 'active')",
            member_id,
            organization_id,
            f"idp-{token()}",
            f"{token()}@example.org",
        )
        self.members.append(member_id)
        if admin_role:
            await self.admin.execute(
                "INSERT INTO public.role_grants (id, organization_id, member_id, role_key, scope_type) "
                "VALUES ($1, $2, $3, 'admin', 'organization')",
                uuid.uuid4(),
                organization_id,
                member_id,
            )
        return member_id

    async def channel(self, organization_id: uuid.UUID, *, enabled: bool = True) -> uuid.UUID:
        channel_id = uuid.uuid4()
        await self.admin.execute(
            "INSERT INTO public.notification_channels "
            "(id, organization_id, channel_key, display_name, enabled) "
            "VALUES ($1, $2, 'scripted', 'Scripted', $3)",
            channel_id,
            organization_id,
            enabled,
        )
        self.channels.append(channel_id)
        return channel_id

    async def delivery(
        self,
        organization_id: uuid.UUID,
        channel_id: uuid.UUID,
        member_id: uuid.UUID,
        *,
        status: str = "pending",
        attempts: int = 0,
        template_key: str = "team-member-added",
        claimed_by: str | None = None,
        claimed_at: datetime | None = None,
        entity_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        delivery_id, event_id = uuid.uuid4(), uuid.uuid4()
        self.event_ids.append(event_id)
        await self.admin.execute(
            "INSERT INTO public.notification_deliveries "
            "(id, organization_id, channel_id, channel_key, event_id, recipient_member_id, target, "
            "idempotency_key, status, attempts, claimed_by, claimed_at, template_key, event_type, "
            "entity_type, entity_id, message_data) "
            "VALUES ($1, $2, $3, 'scripted', $4, $5, $6, $7, $8, $9, $10, $11, $12, 'team_member.added', "
            "'team', $13, $14::jsonb)",
            delivery_id,
            organization_id,
            channel_id,
            event_id,
            member_id,
            str(member_id),
            f"key-{delivery_id}",
            status,
            attempts,
            claimed_by,
            claimed_at,
            template_key,
            entity_id,
            json.dumps({"team_id": str(uuid.uuid4()), "member_id": str(member_id), "team_role": "member"}),
        )
        return delivery_id

    async def row(self, delivery_id: uuid.UUID) -> asyncpg.Record:
        row = await self.admin.fetchrow(
            "SELECT * FROM public.notification_deliveries WHERE id = $1", delivery_id
        )
        assert row is not None
        return row

    def deps(self, script: Script, *, breakers: CircuitRegistry | None = None) -> SenderDeps:
        registry = ChannelRegistry()
        registry.register(_channel_class(script))
        context = ProviderContext(env="test", pillar="secrets", base_dir=self.tmp_path)
        provider = FileSecretsProvider.from_settings({"directory": "secrets"}, context)
        return SenderDeps(
            registry, ChannelRuntime(ChannelCredentialStore(provider)), breakers or CircuitRegistry()
        )

    async def cleanup(self) -> None:
        await self.admin.execute("DELETE FROM public.notification_deliveries")
        await self.admin.execute("DELETE FROM public.notifications")
        await self.admin.execute("DELETE FROM public.notification_channels")
        await self.admin.execute("DELETE FROM public.role_grants WHERE member_id = ANY($1)", self.members)
        await self.admin.execute(
            "DELETE FROM public.outbox WHERE event_type = 'notification_delivery.dead_lettered'"
        )
        await self.admin.execute("DELETE FROM public.members WHERE id = ANY($1)", self.members)


@pytest.fixture
async def world(isolation_db: IsolationDb, tmp_path: Path) -> AsyncIterator[World]:
    admin = await asyncpg.connect(isolation_db.admin_dsn)
    await World(admin, tmp_path).cleanup()  # a failed earlier run must not leak rows in
    seeded = World(admin, tmp_path)
    yield seeded
    await seeded.cleanup()
    await admin.close()


async def _pass(pool: Pool, deps: SenderDeps, worker: str = "sender-1", **options: Any) -> int:
    return await run_once(pool, deps, worker, SenderOptions(**options))


async def test_a_pending_delivery_is_sent_once(
    make_pool: PoolFactory, isolation_db: IsolationDb, world: World
) -> None:
    org = isolation_db.org_a
    member, channel = await world.member(org), await world.channel(org)
    delivery = await world.delivery(org, channel, member)
    script = Script()
    pool = await make_pool("worker")
    with time_machine.travel(FROZEN, tick=False):
        assert await _pass(pool, world.deps(script)) == 1
        assert await _pass(pool, world.deps(script)) == 0  # a sent delivery is never claimed again
    row = await world.row(delivery)
    assert (row["status"], row["attempts"], row["error_code"]) == ("sent", 1, None)
    assert script.calls == [(str(org), str(member), f"key-{delivery}")]


async def test_a_failing_channel_gets_three_attempts_then_dead_letters_with_its_effects(
    make_pool: PoolFactory, isolation_db: IsolationDb, world: World
) -> None:
    org = isolation_db.org_a
    admin_member, member = await world.member(org, admin_role=True), await world.member(org)
    channel, entity = await world.channel(org), uuid.uuid4()
    delivery = await world.delivery(org, channel, member, entity_id=entity)
    script = Script([failure_from_status(503)])
    deps, pool = world.deps(script), await make_pool("worker")

    with time_machine.travel(NOW, tick=False) as clock:
        assert await _pass(pool, deps) == 1
        row = await world.row(delivery)
        assert (row["status"], row["attempts"], row["error_code"]) == ("failed", 1, "http_503")
        assert row["next_retry_at"] == NOW + timedelta(seconds=1)

        assert await _pass(pool, deps) == 0  # the 1 s backoff has not passed
        clock.shift(timedelta(seconds=2))
        assert await _pass(pool, deps) == 1
        row = await world.row(delivery)
        assert (row["status"], row["attempts"]) == ("failed", 2)
        assert row["next_retry_at"] == NOW + timedelta(seconds=2 + 4)

        clock.shift(timedelta(seconds=5))
        assert await _pass(pool, deps) == 1
        assert await _pass(pool, deps) == 0

    row = await world.row(delivery)
    assert (row["status"], row["attempts"], row["error_code"]) == ("dead_lettered", 3, "http_503")
    assert len(script.calls) == 3
    alerts = await world.admin.fetch(
        "SELECT member_id, template_key, body FROM public.notifications WHERE event_type = $1",
        "notification_delivery.dead_lettered",
    )
    assert [(a["member_id"], a["template_key"]) for a in alerts] == [(admin_member, "delivery-dead-lettered")]
    assert "scripted" in alerts[0]["body"]
    audit = await world.admin.fetchrow(
        "SELECT entity_type, entity_id FROM public.audit_events WHERE action = $1 AND entity_id = $2",
        "notification_delivery.dead_lettered",
        entity,
    )
    assert audit is not None
    assert (
        await world.admin.fetchval(
            "SELECT count(*) FROM public.outbox WHERE event_type = 'notification_delivery.dead_lettered' "
            "AND aggregate_id = $1",
            delivery,
        )
        == 1
    )


@pytest.mark.parametrize("status", [400, 401, 404, 422])
async def test_a_4xx_is_never_retried(
    make_pool: PoolFactory, isolation_db: IsolationDb, world: World, status: int
) -> None:
    org = isolation_db.org_a
    member, channel = await world.member(org), await world.channel(org)
    delivery = await world.delivery(org, channel, member)
    script = Script([failure_from_status(status)])
    with time_machine.travel(FROZEN, tick=False):
        await _pass(await make_pool("worker"), world.deps(script))
    row = await world.row(delivery)
    assert (row["status"], row["attempts"], row["error_code"]) == ("dead_lettered", 1, f"http_{status}")
    assert len(script.calls) == 1


async def test_timeouts_and_connection_errors_are_retried(
    make_pool: PoolFactory, isolation_db: IsolationDb, world: World
) -> None:
    org = isolation_db.org_a
    member, channel = await world.member(org), await world.channel(org)
    timed_out, refused = (
        await world.delivery(org, channel, member),
        await world.delivery(org, channel, member),
    )
    script = Script([TimeoutError(), ConnectionRefusedError()])
    with time_machine.travel(FROZEN, tick=False):
        await _pass(
            await make_pool("worker"), world.deps(script, breakers=CircuitRegistry(failure_threshold=99))
        )
    rows = {(await world.row(i))["error_code"] for i in (timed_out, refused)}
    assert rows == {"timeout", "connection_error"}
    assert {(await world.row(i))["status"] for i in (timed_out, refused)} == {"failed"}


async def test_the_kill_switch_skips_without_sending_and_keeps_the_installation(
    make_pool: PoolFactory, isolation_db: IsolationDb, world: World
) -> None:
    org = isolation_db.org_a
    member, channel = await world.member(org), await world.channel(org, enabled=False)
    delivery = await world.delivery(org, channel, member)
    script = Script()
    with time_machine.travel(FROZEN, tick=False):
        await _pass(await make_pool("worker"), world.deps(script))
    row = await world.row(delivery)
    assert (row["status"], row["error_code"], row["attempts"]) == ("skipped", "channel.disabled", 0)
    assert script.calls == []
    assert (
        await world.admin.fetchval("SELECT count(*) FROM public.notification_channels WHERE id = $1", channel)
        == 1
    )


async def test_an_unregistered_channel_is_skipped(
    make_pool: PoolFactory, isolation_db: IsolationDb, world: World
) -> None:
    org = isolation_db.org_a
    member, channel = await world.member(org), await world.channel(org)
    delivery = await world.delivery(org, channel, member)
    deps = SenderDeps(ChannelRegistry(), world.deps(Script()).runtime, CircuitRegistry())
    with time_machine.travel(FROZEN, tick=False):
        await _pass(await make_pool("worker"), deps)
    assert (await world.row(delivery))["error_code"] == "channel.unknown"


async def test_an_unrenderable_template_dead_letters_without_sending(
    make_pool: PoolFactory, isolation_db: IsolationDb, world: World
) -> None:
    org = isolation_db.org_a
    member, channel = await world.member(org), await world.channel(org)
    delivery = await world.delivery(org, channel, member, template_key="no-such-template")
    script = Script()
    with time_machine.travel(FROZEN, tick=False):
        await _pass(await make_pool("worker"), world.deps(script))
    row = await world.row(delivery)
    assert (row["status"], row["error_code"]) == ("dead_lettered", "template.invalid")
    assert script.calls == []


async def test_two_senders_at_once_send_each_delivery_once(
    make_pool: PoolFactory, isolation_db: IsolationDb, world: World
) -> None:
    org = isolation_db.org_a
    member, channel = await world.member(org), await world.channel(org)
    ids = [await world.delivery(org, channel, member) for _ in range(12)]
    script = Script(delay=0.01)
    pool_a, pool_b = await make_pool("worker"), await make_pool("worker")
    with time_machine.travel(FROZEN, tick=False):
        await asyncio.gather(
            _pass(pool_a, world.deps(script), "sender-a", batch_size=4),
            _pass(pool_b, world.deps(script), "sender-b", batch_size=4),
        )
        await asyncio.gather(
            _pass(pool_a, world.deps(script), "sender-a", batch_size=20),
            _pass(pool_b, world.deps(script), "sender-b", batch_size=20),
        )
    keys = [call[2] for call in script.calls]
    assert sorted(keys) == sorted(f"key-{i}" for i in ids)
    assert {(await world.row(i))["status"] for i in ids} == {"sent"}


async def test_a_claim_left_by_a_dead_worker_is_resent_exactly_once(
    make_pool: PoolFactory, isolation_db: IsolationDb, world: World
) -> None:
    """The one documented resend: a worker died after send, before it recorded the result."""
    org = isolation_db.org_a
    member, channel = await world.member(org), await world.channel(org)
    delivery = await world.delivery(
        org,
        channel,
        member,
        status="sending",
        attempts=1,
        claimed_by="dead-worker",
        claimed_at=NOW - timedelta(minutes=6),
    )
    fresh = await world.delivery(
        org,
        channel,
        member,
        status="sending",
        attempts=1,
        claimed_by="busy-worker",
        claimed_at=NOW - timedelta(seconds=30),
    )
    script = Script()
    pool = await make_pool("worker")
    with time_machine.travel(NOW, tick=False):
        await _pass(pool, world.deps(script))
        await _pass(pool, world.deps(script))
    assert [call[2] for call in script.calls] == [f"key-{delivery}"]
    assert (await world.row(delivery))["status"] == "sent"
    assert (await world.row(fresh))["status"] == "sending"  # still held by a live worker


async def test_a_stale_claim_that_used_its_last_attempt_dead_letters_without_sending(
    make_pool: PoolFactory, isolation_db: IsolationDb, world: World
) -> None:
    org = isolation_db.org_a
    admin_member, member = await world.member(org, admin_role=True), await world.member(org)
    channel = await world.channel(org)
    delivery = await world.delivery(
        org,
        channel,
        member,
        status="sending",
        attempts=3,
        claimed_by="dead-worker",
        claimed_at=NOW - timedelta(minutes=10),
    )
    script = Script()
    with time_machine.travel(NOW, tick=False):
        await _pass(await make_pool("worker"), world.deps(script))
    row = await world.row(delivery)
    assert (row["status"], row["error_code"]) == ("dead_lettered", "worker_interrupted")
    assert script.calls == []
    assert (
        await world.admin.fetchval(
            "SELECT count(*) FROM public.notifications WHERE member_id = $1", admin_member
        )
        == 1
    )


async def test_an_open_circuit_keeps_deliveries_queued_and_does_not_count_the_attempt(
    make_pool: PoolFactory, isolation_db: IsolationDb, world: World
) -> None:
    org = isolation_db.org_a
    member, channel = await world.member(org), await world.channel(org)
    ids = [await world.delivery(org, channel, member) for _ in range(7)]
    script = Script([failure_from_status(503)])
    deps, pool = world.deps(script), await make_pool("worker")
    with time_machine.travel(NOW, tick=False) as clock:
        await _pass(pool, deps, batch_size=7)
        assert len(script.calls) == 5  # five consecutive failures open the circuit
        rows = [await world.row(i) for i in ids]
        held = [r for r in rows if r["attempts"] == 0]
        assert len(held) == 2
        assert {r["status"] for r in held} == {"pending"}
        assert {r["next_retry_at"] for r in held} == {NOW + timedelta(seconds=30)}

        clock.shift(timedelta(seconds=31))
        script.outcomes = [DeliveryResult(delivered=True)]
        script.calls.clear()
        await _pass(pool, deps, batch_size=20)
    assert len(script.calls) >= 1  # the half-open trial went through and closed the circuit
    assert (await world.row(held[0]["id"]))["status"] == "sent"


async def test_each_organization_is_sent_under_its_own_context(
    make_pool: PoolFactory, isolation_db: IsolationDb, world: World
) -> None:
    member_a, member_b = await world.member(isolation_db.org_a), await world.member(isolation_db.org_b)
    channel_a, channel_b = await world.channel(isolation_db.org_a), await world.channel(isolation_db.org_b)
    delivery_a = await world.delivery(isolation_db.org_a, channel_a, member_a)
    delivery_b = await world.delivery(isolation_db.org_b, channel_b, member_b)
    script = Script()
    with time_machine.travel(FROZEN, tick=False):
        await _pass(await make_pool("worker"), world.deps(script))
    seen = {(call[0], call[2]) for call in script.calls}
    assert seen == {
        (str(isolation_db.org_a), f"key-{delivery_a}"),
        (str(isolation_db.org_b), f"key-{delivery_b}"),
    }
