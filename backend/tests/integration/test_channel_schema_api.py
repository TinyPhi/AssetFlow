# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The channel settings schema endpoint, and its agreement with the server's validation (M1.5-T8).

A payload that is valid against the exported schema is accepted by the installation API, and an
invalid one is a 422 whose `errors[]` paths name the schema's own property names.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx
import pytest
from jsonschema import Draft202012Validator
from pg_harness import IsolationDb, PoolFactory

from app.channels.email import EmailChannel
from app.channels.inapp import InAppChannel
from app.channels.registry import ChannelRegistry
from app.channels.webhook import WebhookChannel
from app.core.db import Pool, tenant_transaction
from app.main import create_app
from app.providers.auth.mock import MockAuthProvider
from app.providers.context import ProviderContext
from app.providers.secrets.file import FileSecretsProvider
from app.providers.telemetry.noop import NoOpTelemetryProvider

BASE = "/api/v1/notification-channels"
GOOD_WEBHOOK = {
    "url": "https://hooks.example.test/in",
    "events": ["team_member.added"],
    "field_mapping": {"member": "member_id"},
}


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
    await conn.execute("DELETE FROM public.notification_channels")
    await conn.execute("DELETE FROM public.outbox WHERE event_type LIKE 'notification_channel.%'")
    await conn.close()


async def _admin(pool: Pool, org_id: UUID) -> dict[str, str]:
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
    return {
        "x-organization-id": str(org_id),
        "x-member-id": str(member_id),
        "x-role": "admin",
        "x-scope-type": "organization",
    }


async def _schema(client: httpx.AsyncClient, headers: dict[str, str], key: str) -> dict[str, Any]:
    res = await client.get(f"{BASE}/{key}/schema", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()["data"]  # type: ignore[no-any-return]


async def test_each_channels_schema_is_served_with_secrets_marked_write_only(
    client: httpx.AsyncClient, make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    headers = await _admin(await make_pool("api"), isolation_db.org_a)
    for key, secrets in (("inapp", []), ("email", []), ("webhook", ["signing_secret"])):
        schema = await _schema(client, headers, key)
        Draft202012Validator.check_schema(schema)
        assert schema["$id"] == f"/api/v1/notification-channels/{key}/schema"
        marked = [n for n, p in schema.get("properties", {}).items() if p.get("x-assetflow-secret")]
        assert marked == secrets
        for name in secrets:
            assert schema["properties"][name]["writeOnly"] is True


async def test_the_etag_lets_a_client_skip_an_unchanged_schema(
    client: httpx.AsyncClient, make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    headers = await _admin(await make_pool("api"), isolation_db.org_a)
    first = await client.get(f"{BASE}/webhook/schema", headers=headers)
    etag = first.headers["etag"]
    assert etag.startswith('"')
    same = await client.get(f"{BASE}/webhook/schema", headers={**headers, "if-none-match": etag})
    assert same.status_code == 304
    assert same.content == b""
    other = await client.get(f"{BASE}/email/schema", headers={**headers, "if-none-match": etag})
    assert other.status_code == 200
    assert other.headers["etag"] != etag


async def test_an_unknown_channel_is_404_and_a_caller_without_the_permission_is_404(
    client: httpx.AsyncClient, make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    headers = await _admin(await make_pool("api"), isolation_db.org_a)
    unknown = await client.get(f"{BASE}/no-such-channel/schema", headers=headers)
    assert (unknown.status_code, unknown.json()["code"]) == (404, "notification_channel.not_found")
    member = {**headers, "x-role": "member"}
    assert (await client.get(f"{BASE}/webhook/schema", headers=member)).status_code == 404
    assert (await client.get(f"{BASE}/webhook/schema")).status_code == 401


async def test_a_payload_valid_against_the_schema_is_accepted_and_an_invalid_one_names_the_schemas_fields(
    client: httpx.AsyncClient,
    make_pool: PoolFactory,
    isolation_db: IsolationDb,
    admin_db: asyncpg.Connection[asyncpg.Record],
) -> None:
    headers = await _admin(await make_pool("api"), isolation_db.org_a)
    schema = await _schema(client, headers, "webhook")
    validator = Draft202012Validator(schema)
    secret = "a-secret-of-sixteen+"
    valid = {**GOOD_WEBHOOK, "signing_secret": secret}
    assert list(validator.iter_errors(valid)) == []

    accepted = await client.post(
        f"{BASE}/installations",
        headers=headers,
        json={"channel_key": "webhook", "settings": GOOD_WEBHOOK, "secrets": {"signing_secret": secret}},
    )
    assert accepted.status_code == 201, accepted.text
    await admin_db.execute("DELETE FROM public.notification_channels")

    invalid = {**GOOD_WEBHOOK, "events": [], "url": "http://hooks.example.test/in"}
    assert list(validator.iter_errors({**invalid, "signing_secret": secret})) != []
    rejected = await client.post(
        f"{BASE}/installations",
        headers=headers,
        json={"channel_key": "webhook", "settings": invalid, "secrets": {"signing_secret": secret}},
    )
    assert rejected.status_code == 422
    fields = {e["field"] for e in rejected.json()["errors"]}
    assert fields
    for field in fields:
        assert field.startswith("body.settings.")
        assert field.removeprefix("body.settings.").split(".")[0] in schema["properties"]
    assert {"body.settings.events", "body.settings.url"} <= fields


async def test_an_installation_never_returns_a_secret_value_for_any_channel(
    client: httpx.AsyncClient,
    make_pool: PoolFactory,
    isolation_db: IsolationDb,
    admin_db: asyncpg.Connection[asyncpg.Record],
) -> None:
    headers = await _admin(await make_pool("api"), isolation_db.org_a)
    secret = "a-secret-of-sixteen+"
    created = await client.post(
        f"{BASE}/installations",
        headers=headers,
        json={"channel_key": "webhook", "settings": GOOD_WEBHOOK, "secrets": {"signing_secret": secret}},
    )
    texts = [
        created.text,
        (await client.get(f"{BASE}/installations", headers=headers)).text,
        (await client.get(f"{BASE}/installations/{created.json()['data']['id']}", headers=headers)).text,
    ]
    for text in texts:
        assert secret not in text
        assert '"signing_secret":{"set":true}' in text.replace(" ", "")
