# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for OpenBao Secrets Provider (§B6.1, §B6.2, M1.3-T9)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core.config import ConfigError
from app.core.problems import SecretsUnavailableError
from app.providers.context import ProviderContext
from app.providers.secrets.openbao import OpenBaoSecretsProvider


async def test_openbao_invalid_ref() -> None:
    ctx = ProviderContext(env="test", pillar="secrets", base_dir=Path.cwd())
    provider = OpenBaoSecretsProvider.from_settings({"address": "http://localhost:8200"}, ctx)

    with pytest.raises(SecretsUnavailableError, match="Invalid secret reference"):
        await provider.get("invalid_ref")

    with pytest.raises(SecretsUnavailableError, match="Malformed path"):
        await provider.get_map("not_a_secret_uri")


def test_openbao_production_guards() -> None:
    ctx = ProviderContext(env="production", pillar="secrets", base_dir=Path.cwd())
    # Should fail if address is not HTTPS
    with pytest.raises(ConfigError) as exc_info:
        OpenBaoSecretsProvider.from_settings({"address": "http://localhost:8200"}, ctx)
    assert "address must use HTTPS in production" in str(exc_info.value)


async def test_openbao_health() -> None:
    ctx = ProviderContext(env="test", pillar="secrets", base_dir=Path.cwd())
    provider = OpenBaoSecretsProvider.from_settings({"address": "http://localhost:8200"}, ctx)
    health = await provider.health()
    assert health["provider"] == "openbao"


class _Bao:
    """A fake OpenBao KV v2 endpoint: records requests, answers from a handler."""

    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, answer: Callable[[httpx.Request], httpx.Response]
    ) -> None:
        self.requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return answer(request)

        real = httpx.AsyncClient

        def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
            return real(*args, transport=httpx.MockTransport(handler), **kwargs)

        monkeypatch.setattr("app.providers.secrets.openbao.httpx.AsyncClient", factory)


def _provider() -> OpenBaoSecretsProvider:
    ctx = ProviderContext(env="test", pillar="secrets", base_dir=Path.cwd())
    return OpenBaoSecretsProvider.from_settings({"address": "http://bao.test:8200", "token": "t-1"}, ctx)


CHANNEL = "secret://assetflow/orgs/org-a/channels/chan-1"


async def test_openbao_put_writes_the_kv_v2_data_path(monkeypatch: pytest.MonkeyPatch) -> None:
    bao = _Bao(monkeypatch, lambda r: httpx.Response(200, json={"data": {"version": 1}}))
    await _provider().put(CHANNEL, {"token": "abc"})
    request = bao.requests[0]
    assert request.method == "POST"
    assert request.url.path == "/v1/secret/data/assetflow/orgs/org-a/channels/chan-1"
    assert json.loads(request.content) == {"data": {"token": "abc"}}
    assert request.headers["x-vault-token"] == "t-1"


async def test_openbao_get_map_reads_a_nested_name(monkeypatch: pytest.MonkeyPatch) -> None:
    bao = _Bao(monkeypatch, lambda r: httpx.Response(200, json={"data": {"data": {"token": "abc"}}}))
    assert await _provider().get_map(CHANNEL) == {"token": "abc"}
    assert bao.requests[0].url.path == "/v1/secret/data/assetflow/orgs/org-a/channels/chan-1"


async def test_openbao_patch_sends_a_kv_v2_merge_patch(monkeypatch: pytest.MonkeyPatch) -> None:
    bao = _Bao(monkeypatch, lambda r: httpx.Response(200, json={"data": {"version": 2}}))
    await _provider().patch(CHANNEL, {"token": "abc", "signing_key": None})
    request = bao.requests[0]
    assert request.method == "PATCH"
    assert request.headers["content-type"] == "application/merge-patch+json"
    assert request.url.path == "/v1/secret/data/assetflow/orgs/org-a/channels/chan-1"
    assert json.loads(request.content) == {"data": {"token": "abc", "signing_key": None}}


@pytest.mark.parametrize("status", [403, 404, 500])
async def test_openbao_patch_refused_is_a_generic_error(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    _Bao(monkeypatch, lambda r: httpx.Response(status, json={"errors": ["token abc denied"]}))
    with pytest.raises(SecretsUnavailableError) as exc:
        await _provider().patch(CHANNEL, {"token": "abc"})
    assert "abc" not in str(exc.value)


@pytest.mark.parametrize("status", [403, 404, 500])
async def test_openbao_put_refused_is_a_generic_error(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    _Bao(monkeypatch, lambda r: httpx.Response(status, json={"errors": ["token abc denied"]}))
    with pytest.raises(SecretsUnavailableError) as exc:
        await _provider().put(CHANNEL, {"token": "abc"})
    assert "abc" not in str(exc.value)


@pytest.mark.parametrize("path", ["secret://area", "secret://area/../x", "secret://area//x", "area/name"])
async def test_openbao_put_refuses_malformed_paths(path: str) -> None:
    with pytest.raises(SecretsUnavailableError):
        await _provider().put(path, {"k": "v"})
