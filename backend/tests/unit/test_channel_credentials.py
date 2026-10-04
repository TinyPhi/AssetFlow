# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Channel credential storage and the runtime that reads them (§B6.3 rule 1, §B11.4)."""

from __future__ import annotations

import logging
import secrets as pysecrets
import uuid
from pathlib import Path
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from app.channels.base import ChannelContext, DeliveryResult, NotificationChannel, RenderedMessage
from app.channels.credentials import ChannelCredentialStore, channel_secret_ref
from app.channels.egress import EgressClient
from app.channels.runtime import ChannelRuntime
from app.core.problems import SecretsUnavailableError
from app.providers.context import ProviderContext
from app.providers.secrets.file import FileSecretsProvider

ORG = uuid.uuid4()
CHANNEL = uuid.uuid4()


class _Settings(BaseModel):
    pass


class _WithSecrets(NotificationChannel):
    key: ClassVar[str] = "with-secrets"
    config_schema: ClassVar[type[BaseModel]] = _Settings
    secret_fields: ClassVar[tuple[str, ...]] = ("token",)
    egress_hosts: ClassVar[tuple[str, ...]] = ("hooks.example.test",)

    async def send(
        self, ctx: ChannelContext, target: str, message: RenderedMessage, idempotency_key: str
    ) -> DeliveryResult:
        raise NotImplementedError

    async def health(self, ctx: ChannelContext) -> dict[str, Any]:
        return {"healthy": True}


class _NoSecrets(_WithSecrets):
    key: ClassVar[str] = "no-secrets"
    secret_fields: ClassVar[tuple[str, ...]] = ()


@pytest.fixture
def provider(tmp_path: Path) -> FileSecretsProvider:
    context = ProviderContext(env="test", pillar="secrets", base_dir=tmp_path)
    return FileSecretsProvider.from_settings({"directory": "secrets"}, context)


@pytest.fixture
def store(provider: FileSecretsProvider) -> ChannelCredentialStore:
    return ChannelCredentialStore(provider)


def test_the_reference_is_the_openbao_channel_path() -> None:
    assert channel_secret_ref(ORG, CHANNEL) == f"secret://assetflow/orgs/{ORG}/channels/{CHANNEL}"


@pytest.mark.parametrize("bad", ["../x", "a/b", "not-a-uuid", ""])
def test_the_reference_only_accepts_uuids(bad: str) -> None:
    with pytest.raises(ValueError, match=r"UUID|badly formed"):
        channel_secret_ref(bad, CHANNEL)
    with pytest.raises(ValueError, match=r"UUID|badly formed"):
        channel_secret_ref(ORG, bad)


async def test_credentials_round_trip_through_the_provider(store: ChannelCredentialStore) -> None:
    token = pysecrets.token_urlsafe(24)
    ref = await store.write(ORG, CHANNEL, {"token": token})
    assert ref == channel_secret_ref(ORG, CHANNEL)
    assert dict(await store.read(ref)) == {"token": token}


async def test_writing_again_replaces_the_credentials(store: ChannelCredentialStore) -> None:
    ref = await store.write(ORG, CHANNEL, {"token": "one", "extra": "x"})
    await store.write(ORG, CHANNEL, {"token": "two"})
    assert dict(await store.read(ref)) == {"token": "two"}


async def test_another_installation_has_its_own_credentials(store: ChannelCredentialStore) -> None:
    other = uuid.uuid4()
    first = await store.write(ORG, CHANNEL, {"token": "first"})
    second = await store.write(ORG, other, {"token": "second"})
    assert dict(await store.read(first)) == {"token": "first"}
    assert dict(await store.read(second)) == {"token": "second"}


async def test_reading_an_unset_credential_fails(store: ChannelCredentialStore) -> None:
    with pytest.raises(SecretsUnavailableError):
        await store.read(channel_secret_ref(ORG, CHANNEL))


async def test_the_runtime_supplies_credentials_and_a_client(store: ChannelCredentialStore) -> None:
    token = pysecrets.token_urlsafe(24)
    ref = await store.write(ORG, CHANNEL, {"token": token})
    installation = {"id": str(CHANNEL), "secret_ref": ref, "allowed_hosts": ["extra.example.test"]}
    ctx = await ChannelRuntime(store).build_context(_WithSecrets(), str(ORG), installation)
    assert ctx.credentials["token"] == token
    assert isinstance(ctx.http, EgressClient)


async def test_the_runtime_reads_no_credentials_for_a_channel_without_secret_fields(
    store: ChannelCredentialStore,
) -> None:
    ref = await store.write(ORG, CHANNEL, {"token": "unused"})
    ctx = await ChannelRuntime(store).build_context(_NoSecrets(), str(ORG), {"secret_ref": ref})
    assert dict(ctx.credentials) == {}


async def test_the_credentials_are_read_only(store: ChannelCredentialStore) -> None:
    ref = await store.write(ORG, CHANNEL, {"token": "x"})
    ctx = await ChannelRuntime(store).build_context(_WithSecrets(), str(ORG), {"secret_ref": ref})
    with pytest.raises(TypeError):
        ctx.credentials["token"] = "changed"  # type: ignore[index]


async def test_the_context_repr_never_shows_a_credential(store: ChannelCredentialStore) -> None:
    token = "tok-" + pysecrets.token_hex(12)
    ref = await store.write(ORG, CHANNEL, {"token": token})
    ctx = await ChannelRuntime(store).build_context(_WithSecrets(), str(ORG), {"secret_ref": ref})
    assert token not in repr(ctx)
    assert token not in str(ctx)
    assert token not in f"{ctx!s}{ctx.http!r}"


async def test_no_credential_reaches_the_logs(
    store: ChannelCredentialStore, caplog: pytest.LogCaptureFixture
) -> None:
    token = "tok-" + pysecrets.token_hex(12)
    with caplog.at_level(logging.DEBUG):
        ref = await store.write(ORG, CHANNEL, {"token": token})
        ctx = await ChannelRuntime(store).build_context(_WithSecrets(), str(ORG), {"secret_ref": ref})
        repr(ctx)
        with pytest.raises(SecretsUnavailableError):
            await store.read(channel_secret_ref(ORG, uuid.uuid4()))
    assert token not in caplog.text
