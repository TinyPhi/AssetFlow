# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for OpenBao Secrets Provider (§B6.1, §B6.2, M1.3-T9)."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core.config import ConfigError
from app.core.problems import SecretsUnavailableError
from app.providers.context import ProviderContext
from app.providers.secrets.openbao import OpenBaoSecretsProvider
from tests.contract.secrets.fake_bao import FakeBao


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


async def test_openbao_encrypt_many_sends_one_batch_request(monkeypatch: pytest.MonkeyPatch) -> None:
    bao = _Bao(
        monkeypatch,
        lambda r: httpx.Response(
            200,
            json={
                "data": {
                    "batch_results": [
                        {"ciphertext": "vault:v1:aaa"},
                        {"ciphertext": "vault:v1:bbb"},
                    ]
                }
            },
        ),
    )
    items = [("asset:org-a:ssn", "123-45-6789"), ("asset:org-a:pin", "4321")]
    ciphertexts = await _provider().encrypt_many(items)
    assert ciphertexts == ["vault:v1:aaa", "vault:v1:bbb"]
    assert len(bao.requests) == 1
    body = json.loads(bao.requests[0].content)
    assert len(body["batch_input"]) == 2
    assert body["batch_input"][0]["context"] != body["batch_input"][1]["context"]


async def test_openbao_encrypt_many_of_nothing_sends_no_request(monkeypatch: pytest.MonkeyPatch) -> None:
    bao = _Bao(monkeypatch, lambda r: httpx.Response(200, json={"data": {"batch_results": []}}))
    assert await _provider().encrypt_many([]) == []
    assert bao.requests == []


@pytest.mark.parametrize("status", [403, 500])
async def test_openbao_encrypt_many_refused_is_a_generic_error(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    _Bao(monkeypatch, lambda r: httpx.Response(status, json={"errors": ["denied"]}))
    with pytest.raises(SecretsUnavailableError):
        await _provider().encrypt_many([("ctx", "value-should-not-leak")])


async def test_openbao_encrypt_many_result_count_mismatch_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _Bao(monkeypatch, lambda r: httpx.Response(200, json={"data": {"batch_results": [{"ciphertext": "x"}]}}))
    with pytest.raises(SecretsUnavailableError):
        await _provider().encrypt_many([("ctx-1", "a"), ("ctx-2", "b")])


# ------------------------------------------------------------------------------ token lifecycle


def _approle_provider(tmp_path: Path) -> OpenBaoSecretsProvider:
    (tmp_path / "secret-id").write_text("sid-12345678", encoding="utf-8")
    ctx = ProviderContext(env="test", pillar="secrets", base_dir=tmp_path)
    return OpenBaoSecretsProvider.from_settings(
        {"address": "http://bao.test:8200", "role_id": "role-1", "secret_id_file": "secret-id"}, ctx
    )


async def test_openbao_login_once_and_reuse_while_the_lease_is_fresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bao = FakeBao()
    bao.install(monkeypatch)
    bao.kv["a/b"] = {"k": "v"}
    provider = _approle_provider(tmp_path)
    await provider.get_map("secret://a/b")
    await provider.get_map("secret://a/b")
    assert (bao.logins, bao.renewals) == (1, 0)


async def test_openbao_renews_the_token_before_it_expires(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bao = FakeBao()
    bao.install(monkeypatch)
    bao.kv["a/b"] = {"k": "v"}
    provider = _approle_provider(tmp_path)
    await provider.get_map("secret://a/b")
    provider._token_expires_at = time.monotonic() + 10  # inside the last third of a 3600s lease
    await provider.get_map("secret://a/b")
    assert (bao.logins, bao.renewals) == (1, 1)
    renew = next(r for r in bao.requests if r.url.path == "/v1/auth/token/renew-self")
    assert renew.headers["x-vault-token"] == "t-login-1"
    assert (provider._token_expires_at or 0) - time.monotonic() > 3000


async def test_openbao_logs_in_again_when_renewal_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bao = FakeBao()
    bao.install(monkeypatch)
    bao.kv["a/b"] = {"k": "v"}
    provider = _approle_provider(tmp_path)
    await provider.get_map("secret://a/b")
    bao.valid_tokens.clear()  # renew-self is refused too
    provider._token_expires_at = time.monotonic() + 10
    assert await provider.get_map("secret://a/b") == {"k": "v"}
    assert bao.logins == 2


async def test_openbao_403_triggers_a_fresh_approle_login_and_one_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bao = FakeBao()
    bao.install(monkeypatch)
    bao.kv["a/b"] = {"k": "v"}
    provider = _approle_provider(tmp_path)
    await provider.get_map("secret://a/b")
    bao.valid_tokens.discard("t-login-1")  # revoked server-side before its lease ends
    assert await provider.get_map("secret://a/b") == {"k": "v"}
    assert bao.logins == 2
    gets = [r for r in bao.requests if r.method == "GET"]
    assert [r.headers["x-vault-token"] for r in gets] == ["t-login-1", "t-login-1", "t-login-2"]


async def test_openbao_403_after_relogin_is_not_retried_forever(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bao = FakeBao()
    bao.install(monkeypatch)
    bao.revoke_everything_after_each_call = True
    provider = _approle_provider(tmp_path)
    with pytest.raises(SecretsUnavailableError):
        await provider.get_map("secret://a/b")
    assert bao.logins == 2  # the first login, one fresh login after the 403, then it gives up


async def test_openbao_static_token_403_is_unavailable_without_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bao = FakeBao()
    bao.install(monkeypatch)
    ctx = ProviderContext(env="test", pillar="secrets", base_dir=Path.cwd())
    provider = OpenBaoSecretsProvider.from_settings(
        {"address": "http://bao.test:8200", "token": "revoked"}, ctx
    )
    with pytest.raises(SecretsUnavailableError):
        await provider.get_map("secret://a/b")
    assert bao.logins == 0


# ------------------------------------------------------------------------------ TLS trust (AF-028)


def _capture_verify(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    real = httpx.AsyncClient

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        seen.update(kwargs)
        return real(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))

    monkeypatch.setattr("app.providers.secrets.openbao.httpx.AsyncClient", factory)
    return seen


async def test_openbao_ca_cert_setting_is_passed_as_verify(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BAO_CACERT", raising=False)
    seen = _capture_verify(monkeypatch)
    ctx = ProviderContext(env="test", pillar="secrets", base_dir=tmp_path)
    provider = OpenBaoSecretsProvider.from_settings(
        {"address": "https://bao.test:8200", "token": "t", "ca_cert": "pki/ca.pem"}, ctx
    )
    await provider.health()
    assert seen["verify"] == str(tmp_path / "pki" / "ca.pem")


async def test_openbao_reads_bao_cacert_when_no_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = tmp_path / "env-ca.pem"
    monkeypatch.setenv("BAO_CACERT", str(bundle))
    seen = _capture_verify(monkeypatch)
    ctx = ProviderContext(env="test", pillar="secrets", base_dir=tmp_path)
    provider = OpenBaoSecretsProvider.from_settings({"address": "https://bao.test:8200", "token": "t"}, ctx)
    await provider.health()
    assert seen["verify"] == str(bundle)


async def test_openbao_default_trust_store_without_ca_cert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BAO_CACERT", raising=False)
    seen = _capture_verify(monkeypatch)
    ctx = ProviderContext(env="test", pillar="secrets", base_dir=tmp_path)
    provider = OpenBaoSecretsProvider.from_settings({"address": "https://bao.test:8200", "token": "t"}, ctx)
    await provider.health()
    assert "verify" not in seen
