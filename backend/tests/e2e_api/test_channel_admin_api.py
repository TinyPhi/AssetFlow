# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""E2E API tests for channel installations, the kill switch and the delivery log (§B6.3, M1.5-T6).

The real app and PostgreSQL, a file secrets provider standing in for OpenBao, and a test channel
with one required and one optional secret field (the built-in `inapp` has none).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, ClassVar
from uuid import UUID, uuid4

import asyncpg
import httpx
import pytest
from pg_harness import IsolationDb, PoolFactory
from pydantic import BaseModel, ConfigDict, Field

from app.channels.base import ChannelContext, DeliveryResult, NotificationChannel, RenderedMessage
from app.channels.registry import ChannelRegistry
from app.core.db import Pool, tenant_transaction
from app.main import create_app
from app.providers.auth.mock import MockAuthProvider
from app.providers.context import ProviderContext
from app.providers.secrets.file import FileSecretsProvider
from app.providers.telemetry.noop import NoOpTelemetryProvider

BASE = "/api/v1/notification-channels"
TOKEN = "tok-super-secret-value-123"
SIGNING = "sign-super-secret-value-456"


class _HookSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint: str = Field(min_length=1, max_length=200)
    token: str = Field(min_length=1, json_schema_extra={"writeOnly": True})
    signing_key: str | None = Field(default=None, json_schema_extra={"writeOnly": True})


class _Hook(NotificationChannel):
    key: ClassVar[str] = "hook"
    display_name: ClassVar[str] = "Hook"
    accepts_allowed_hosts: ClassVar[bool] = True
    config_schema: ClassVar[type[BaseModel]] = _HookSettings
    secret_fields: ClassVar[tuple[str, ...]] = ("token", "signing_key")

    async def send(
        self, ctx: ChannelContext, target: str, message: RenderedMessage, idempotency_key: str
    ) -> DeliveryResult:
        return DeliveryResult(delivered=True)

    async def health(self, ctx: ChannelContext) -> dict[str, Any]:
        return {"healthy": True}


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
    channels.register(_Hook)
    from app.channels.inapp import InAppChannel  # noqa: PLC0415 - test wiring only

    channels.register(InAppChannel)
    app.state.channel_registry = channels
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def admin_db(isolation_db: IsolationDb) -> AsyncIterator[asyncpg.Connection[asyncpg.Record]]:
    conn = await asyncpg.connect(isolation_db.admin_dsn)
    await _clean(conn)
    yield conn
    await _clean(conn)
    await conn.close()


async def _clean(conn: asyncpg.Connection[asyncpg.Record]) -> None:
    await conn.execute("DELETE FROM public.notification_deliveries")
    await conn.execute("DELETE FROM public.notification_channels")
    await conn.execute(
        "DELETE FROM public.outbox WHERE event_type LIKE 'notification_channel.%' "
        "OR event_type LIKE 'notification_delivery.%'"
    )


async def _admin(pool: Pool, org_id: UUID) -> UUID:
    member_id = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.members (id, organization_id, email, status, idp_subject, display_name) "
            "VALUES ($1, $2, $3, 'active', $4, 'Admin User')",
            member_id,
            org_id,
            f"{member_id.hex[:8]}@example.test",
            f"sub-{member_id}",
        )
    return member_id


def _as(org_id: UUID, member_id: UUID, role: str = "admin") -> dict[str, str]:
    return {
        "x-organization-id": str(org_id),
        "x-member-id": str(member_id),
        "x-role": role,
        "x-scope-type": "organization",
    }


async def _install(client: httpx.AsyncClient, headers: dict[str, str], **overrides: Any) -> dict[str, Any]:
    body = {
        "channel_key": "hook",
        "settings": {"endpoint": "https://hooks.example.test/in"},
        "secrets": {"token": TOKEN, "signing_key": SIGNING},
        "allowed_hosts": ["hooks.example.test"],
    }
    body.update(overrides)
    res = await client.post(f"{BASE}/installations", headers=headers, json=body)
    assert res.status_code == 201, res.text
    return res.json()["data"]  # type: ignore[no-any-return]


async def _seed_delivery(
    admin_db: asyncpg.Connection[asyncpg.Record],
    org_id: UUID,
    channel_id: UUID,
    *,
    status: str = "dead_lettered",
) -> UUID:
    member_id = uuid4()
    await admin_db.execute(
        "INSERT INTO public.members (id, organization_id, email, status, idp_subject, display_name) "
        "VALUES ($1, $2, $3, 'active', $4, 'Recipient')",
        member_id,
        org_id,
        f"{member_id.hex[:8]}@example.test",
        f"sub-{member_id}",
    )
    delivery_id = uuid4()
    await admin_db.execute(
        "INSERT INTO public.notification_deliveries (id, organization_id, channel_id, channel_key, event_id, "
        "recipient_member_id, target, idempotency_key, status, attempts, error_code) "
        "VALUES ($1, $2, $3, 'hook', $4, $5, $6, $7, $8, 3, 'http_503')",
        delivery_id,
        org_id,
        channel_id,
        uuid4(),
        member_id,
        str(member_id),
        f"key-{delivery_id}",
        status,
    )
    return delivery_id


async def test_an_installed_secret_never_comes_back(
    client: httpx.AsyncClient,
    make_pool: PoolFactory,
    isolation_db: IsolationDb,
    secrets_provider: FileSecretsProvider,
    admin_db: asyncpg.Connection[asyncpg.Record],
) -> None:
    org, admin = isolation_db.org_a, await _admin(await make_pool("api"), isolation_db.org_a)
    headers = _as(org, admin)
    created = await _install(client, headers)

    assert created["secrets"] == {"signing_key": {"set": True}, "token": {"set": True}}
    seen = [
        json.dumps(created),
        (await client.get(f"{BASE}/installations", headers=headers)).text,
        (await client.get(f"{BASE}/installations/{created['id']}", headers=headers)).text,
        (await client.get(BASE, headers=headers)).text,
    ]
    for text in seen:
        assert TOKEN not in text
        assert SIGNING not in text

    audit = await admin_db.fetch(
        "SELECT before_state, after_state FROM public.audit_events WHERE entity_id = $1", UUID(created["id"])
    )
    outbox = await admin_db.fetch(
        "SELECT payload FROM public.outbox WHERE aggregate_id = $1", UUID(created["id"])
    )
    assert audit and outbox
    assert TOKEN not in json.dumps([dict(r) for r in audit], default=str)
    assert TOKEN not in json.dumps([dict(r) for r in outbox], default=str)
    assert "token" in json.dumps(audit[0]["after_state"])  # the field name, as "secrets_changed"

    row = await admin_db.fetchrow(
        "SELECT * FROM public.notification_channels WHERE id = $1", UUID(created["id"])
    )
    assert row is not None
    assert TOKEN not in json.dumps({k: str(v) for k, v in dict(row).items()})
    assert await secrets_provider.get_map(row["secret_ref"]) == {"token": TOKEN, "signing_key": SIGNING}


async def test_available_channels_list_what_can_be_installed(
    client: httpx.AsyncClient, make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    org, admin = isolation_db.org_a, await _admin(await make_pool("api"), isolation_db.org_a)
    res = await client.get(BASE, headers=_as(org, admin))
    assert res.status_code == 200
    by_key = {c["key"]: c for c in res.json()["data"]}
    assert by_key["hook"]["secret_fields"] == ["token", "signing_key"]
    assert by_key["hook"]["accepts_allowed_hosts"] is True
    assert by_key["inapp"]["accepts_allowed_hosts"] is False


async def test_installing_twice_conflicts_and_bad_input_is_422(
    client: httpx.AsyncClient,
    make_pool: PoolFactory,
    isolation_db: IsolationDb,
    admin_db: asyncpg.Connection[asyncpg.Record],
) -> None:
    org, admin = isolation_db.org_a, await _admin(await make_pool("api"), isolation_db.org_a)
    headers = _as(org, admin)
    await _install(client, headers)
    again = await client.post(
        f"{BASE}/installations",
        headers=headers,
        json={"channel_key": "hook", "settings": {"endpoint": "x"}, "secrets": {"token": "t"}},
    )
    assert (again.status_code, again.json()["code"]) == (409, "notification_channel.exists")

    for body in (
        {"channel_key": "nope"},
        {"channel_key": "inapp", "secrets": {"token": "x"}},
        {"channel_key": "inapp", "allowed_hosts": ["a.example.test"]},
        {"channel_key": "hook", "settings": {}, "secrets": {}},
    ):
        res = await client.post(f"{BASE}/installations", headers=headers, json=body)
        assert res.status_code == 422, (body, res.text)


async def test_update_needs_the_current_version_and_secrets_follow_the_rules(
    client: httpx.AsyncClient,
    make_pool: PoolFactory,
    isolation_db: IsolationDb,
    secrets_provider: FileSecretsProvider,
    admin_db: asyncpg.Connection[asyncpg.Record],
) -> None:
    org, admin = isolation_db.org_a, await _admin(await make_pool("api"), isolation_db.org_a)
    headers = _as(org, admin)
    created = await _install(client, headers)
    url = f"{BASE}/installations/{created['id']}"
    ref = await admin_db.fetchval(
        "SELECT secret_ref FROM public.notification_channels WHERE id = $1", UUID(created["id"])
    )

    stale = await client.patch(url, headers=headers, json={"version": 99, "display_name": "x"})
    assert (stale.status_code, stale.json()["code"]) == (409, "notification_channel.version_conflict")

    renamed = await client.patch(url, headers=headers, json={"version": 1, "display_name": "Renamed"})
    assert renamed.status_code == 200
    assert (renamed.json()["data"]["display_name"], renamed.json()["data"]["version"]) == ("Renamed", 2)
    assert await secrets_provider.get_map(ref) == {"token": TOKEN, "signing_key": SIGNING}  # left out: kept

    changed = await client.patch(url, headers=headers, json={"version": 2, "secrets": {"token": "tok-new"}})
    assert changed.status_code == 200
    assert await secrets_provider.get_map(ref) == {"token": "tok-new", "signing_key": SIGNING}

    cleared = await client.patch(url, headers=headers, json={"version": 3, "secrets": {"signing_key": None}})
    assert cleared.status_code == 200
    assert cleared.json()["data"]["secrets"] == {"signing_key": {"set": False}, "token": {"set": True}}
    assert await secrets_provider.get_map(ref) == {"token": "tok-new"}

    required = await client.patch(url, headers=headers, json={"version": 4, "secrets": {"token": None}})
    assert required.status_code == 422  # the token is required: it cannot be cleared
    assert await secrets_provider.get_map(ref) == {"token": "tok-new"}

    audit = await admin_db.fetch(
        "SELECT action, before_state, after_state FROM public.audit_events WHERE entity_id = $1 ORDER BY id",
        UUID(created["id"]),
    )
    assert [a["action"] for a in audit] == ["notification_channel.installed"] + [
        "notification_channel.updated"
    ] * 3
    assert "tok-new" not in json.dumps([dict(a) for a in audit], default=str)


async def test_allowed_hosts_are_lower_case_plain_and_public(
    client: httpx.AsyncClient,
    make_pool: PoolFactory,
    isolation_db: IsolationDb,
    admin_db: asyncpg.Connection[asyncpg.Record],
) -> None:
    org, admin = isolation_db.org_a, await _admin(await make_pool("api"), isolation_db.org_a)
    headers = _as(org, admin)
    created = await _install(client, headers, allowed_hosts=["Hooks.Example.Test", "api.example.test."])
    assert created["allowed_hosts"] == ["api.example.test", "hooks.example.test"]
    url = f"{BASE}/installations/{created['id']}"
    for bad in (
        ["*.example.test"],
        ["10.0.0.1"],
        ["127.0.0.1"],
        ["169.254.169.254"],
        ["host:8080"],
        ["a/b"],
        [""],
    ):
        res = await client.patch(url, headers=headers, json={"version": 1, "allowed_hosts": bad})
        assert res.status_code == 422, (bad, res.text)
    ok = await client.patch(url, headers=headers, json={"version": 1, "allowed_hosts": ["93.184.216.34"]})
    assert ok.status_code == 200


async def test_the_kill_switch_disables_and_enables_without_deleting(
    client: httpx.AsyncClient,
    make_pool: PoolFactory,
    isolation_db: IsolationDb,
    admin_db: asyncpg.Connection[asyncpg.Record],
) -> None:
    org, admin = isolation_db.org_a, await _admin(await make_pool("api"), isolation_db.org_a)
    headers = _as(org, admin)
    created = await _install(client, headers)
    base = f"{BASE}/installations/{created['id']}"

    off = await client.post(f"{base}/disable", headers=headers)
    assert (off.status_code, off.json()["data"]["enabled"], off.json()["data"]["version"]) == (200, False, 2)
    again = await client.post(f"{base}/disable", headers=headers)
    assert again.json()["data"]["version"] == 2  # already off: nothing changes, nothing is audited
    on = await client.post(f"{base}/enable", headers=headers)
    assert (on.json()["data"]["enabled"], on.json()["data"]["version"]) == (True, 3)

    actions = [
        r["action"]
        for r in await admin_db.fetch(
            "SELECT action FROM public.audit_events WHERE entity_id = $1 ORDER BY id", UUID(created["id"])
        )
    ]
    assert actions == [
        "notification_channel.installed",
        "notification_channel.disabled",
        "notification_channel.enabled",
    ]
    assert await admin_db.fetchval("SELECT count(*) FROM public.notification_channels") == 1
    assert (await client.post(f"{BASE}/installations/{uuid4()}/disable", headers=headers)).status_code == 404


async def test_the_delivery_log_filters_and_pages(
    client: httpx.AsyncClient,
    make_pool: PoolFactory,
    isolation_db: IsolationDb,
    admin_db: asyncpg.Connection[asyncpg.Record],
) -> None:
    org, admin = isolation_db.org_a, await _admin(await make_pool("api"), isolation_db.org_a)
    headers = _as(org, admin)
    created = await _install(client, headers)
    channel_id = UUID(created["id"])
    dead = [await _seed_delivery(admin_db, org, channel_id) for _ in range(3)]
    sent = await _seed_delivery(admin_db, org, channel_id, status="sent")

    everything = (await client.get(f"{BASE}/deliveries", headers=headers)).json()["data"]
    assert {i["id"] for i in everything["items"]} == {str(d) for d in [*dead, sent]}
    only_dead = (await client.get(f"{BASE}/deliveries?status=dead_lettered", headers=headers)).json()["data"]
    assert {i["id"] for i in only_dead["items"]} == {str(d) for d in dead}
    assert only_dead["items"][0]["error_code"] == "http_503"
    assert (await client.get(f"{BASE}/deliveries?channel=other", headers=headers)).json()["data"][
        "items"
    ] == []

    page_one = (await client.get(f"{BASE}/deliveries?limit=3", headers=headers)).json()["data"]
    assert len(page_one["items"]) == 3
    assert page_one["next_cursor"]
    page_two = (
        await client.get(f"{BASE}/deliveries?limit=3&after={page_one['next_cursor']}", headers=headers)
    ).json()["data"]
    assert len(page_two["items"]) == 1
    assert {i["id"] for i in page_one["items"]} | {i["id"] for i in page_two["items"]} == {
        str(d) for d in [*dead, sent]
    }
    assert (await client.get(f"{BASE}/deliveries?after=garbage", headers=headers)).status_code == 422
    future = (await client.get(f"{BASE}/deliveries?since=2999-01-01T00:00:00Z", headers=headers)).json()[
        "data"
    ]
    assert future["items"] == []


async def test_requeue_resets_a_dead_letter_and_refuses_anything_else(
    client: httpx.AsyncClient,
    make_pool: PoolFactory,
    isolation_db: IsolationDb,
    admin_db: asyncpg.Connection[asyncpg.Record],
) -> None:
    org, admin = isolation_db.org_a, await _admin(await make_pool("api"), isolation_db.org_a)
    headers = _as(org, admin)
    channel_id = UUID((await _install(client, headers))["id"])
    dead, sent = (
        await _seed_delivery(admin_db, org, channel_id),
        await _seed_delivery(admin_db, org, channel_id, status="sent"),
    )

    res = await client.post(f"{BASE}/deliveries/{dead}/requeue", headers=headers)
    assert res.status_code == 200
    assert (
        res.json()["data"]["status"],
        res.json()["data"]["attempts"],
        res.json()["data"]["error_code"],
    ) == (
        "pending",
        0,
        None,
    )
    again = await client.post(f"{BASE}/deliveries/{dead}/requeue", headers=headers)
    assert (again.status_code, again.json()["code"]) == (409, "notification_delivery.not_dead_lettered")
    assert (await client.post(f"{BASE}/deliveries/{sent}/requeue", headers=headers)).status_code == 409
    assert (await client.post(f"{BASE}/deliveries/{uuid4()}/requeue", headers=headers)).status_code == 404
    assert (
        await admin_db.fetchval(
            "SELECT count(*) FROM public.audit_events "
            "WHERE action = 'notification_delivery.requeued' AND entity_id = $1",
            dead,
        )
        == 1
    )


async def test_a_member_without_the_permission_cannot_read_or_change(
    client: httpx.AsyncClient,
    make_pool: PoolFactory,
    isolation_db: IsolationDb,
    admin_db: asyncpg.Connection[asyncpg.Record],
) -> None:
    org, admin = isolation_db.org_a, await _admin(await make_pool("api"), isolation_db.org_a)
    created = await _install(client, _as(org, admin))
    channel_id = UUID(created["id"])
    delivery = await _seed_delivery(admin_db, org, channel_id)
    member = _as(org, uuid4(), role="member")
    url = f"{BASE}/installations/{created['id']}"

    for read in (BASE, f"{BASE}/installations", url, f"{BASE}/deliveries"):
        assert (await client.get(read, headers=member)).status_code == 404, read
    writes = [
        client.post(f"{BASE}/installations", headers=member, json={"channel_key": "inapp"}),
        client.patch(url, headers=member, json={"version": 1, "display_name": "x"}),
        client.post(f"{url}/disable", headers=member),
        client.post(f"{url}/enable", headers=member),
        client.post(f"{BASE}/deliveries/{delivery}/requeue", headers=member),
    ]
    for pending in writes:
        assert (await pending).status_code == 403
    assert (await client.get(BASE)).status_code == 401


async def test_another_organization_cannot_see_or_change_an_installation_or_its_deliveries(
    client: httpx.AsyncClient,
    make_pool: PoolFactory,
    isolation_db: IsolationDb,
    admin_db: asyncpg.Connection[asyncpg.Record],
) -> None:
    pool = await make_pool("api")
    org_a, org_b = isolation_db.org_a, isolation_db.org_b
    admin_a, admin_b = await _admin(pool, org_a), await _admin(pool, org_b)
    created = await _install(client, _as(org_a, admin_a))
    delivery = await _seed_delivery(admin_db, org_a, UUID(created["id"]))
    b = _as(org_b, admin_b)
    url = f"{BASE}/installations/{created['id']}"

    assert (await client.get(url, headers=b)).status_code == 404
    assert (await client.patch(url, headers=b, json={"version": 1, "display_name": "x"})).status_code == 404
    assert (await client.post(f"{url}/disable", headers=b)).status_code == 404
    assert (await client.post(f"{url}/enable", headers=b)).status_code == 404
    assert (await client.post(f"{BASE}/deliveries/{delivery}/requeue", headers=b)).status_code == 404
    assert (await client.get(f"{BASE}/installations", headers=b)).json()["data"] == []
    assert (await client.get(f"{BASE}/deliveries", headers=b)).json()["data"]["items"] == []

    untouched = await admin_db.fetchrow(
        "SELECT enabled, version, display_name FROM public.notification_channels WHERE id = $1",
        UUID(created["id"]),
    )
    assert untouched is not None
    assert (untouched["enabled"], untouched["version"]) == (True, 1)
    assert (
        await admin_db.fetchval("SELECT status FROM public.notification_deliveries WHERE id = $1", delivery)
        == "dead_lettered"
    )
