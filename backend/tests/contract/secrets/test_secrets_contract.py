# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""SecretsProvider contract suite (§B6.1 rule 2) plus ``file``-specific checks.

Every secrets implementation is added to IMPLEMENTATIONS with a way to seed values. All secret
values here are random, generated at test time.
"""

from __future__ import annotations

import base64
import json
import os
import secrets as pysecrets
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.core.config import ConfigError
from app.core.problems import SecretsUnavailableError
from app.providers.context import ProviderContext
from app.providers.secrets.base import SecretDecryptionError, SecretsProvider
from app.providers.secrets.file import CIPHERTEXT_PREFIX, FileSecretsProvider
from app.providers.secrets.openbao import OpenBaoSecretsProvider
from tests.contract.secrets.fake_bao import FakeBao


def ctx(base_dir: Path, env: str = "test") -> ProviderContext:
    return ProviderContext(env=env, pillar="secrets", base_dir=base_dir)  # type: ignore[arg-type]


@dataclass
class Harness:
    provider: SecretsProvider
    seed: Callable[[str, str, str, str], None]  # area, name, key, value


def _file_harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Harness:
    root = tmp_path / "secrets"
    (root / "transit").mkdir(parents=True)
    (root / "transit" / "file.key").write_bytes(base64.b64encode(os.urandom(32)))

    def seed(area: str, name: str, key: str, value: str) -> None:
        folder = root / area / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / key).write_text(value + "\n", encoding="utf-8")

    provider = FileSecretsProvider.from_settings(
        {"directory": "secrets", "encryption_key_file": "transit/file.key"}, ctx(tmp_path)
    )
    return Harness(provider, seed)


def _openbao_harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Harness:
    bao = FakeBao()
    bao.install(monkeypatch)

    def seed(area: str, name: str, key: str, value: str) -> None:
        bao.kv.setdefault(f"{area}/{name}", {})[key] = value

    provider = OpenBaoSecretsProvider.from_settings(
        {"address": "http://bao.test:8200", "token": "t-1"}, ctx(tmp_path)
    )
    return Harness(provider, seed)


IMPLEMENTATIONS: list[tuple[str, Callable[[Path, pytest.MonkeyPatch], Harness]]] = [
    ("file", _file_harness),
    ("openbao", _openbao_harness),
]


@pytest.fixture(params=IMPLEMENTATIONS, ids=[i[0] for i in IMPLEMENTATIONS])
def harness(request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Harness:
    factory: Callable[[Path, pytest.MonkeyPatch], Harness] = request.param[1]
    return factory(tmp_path, monkeypatch)


# ------------------------------------------------------------------------------ shared contract


async def test_interface_version(harness: Harness) -> None:
    assert isinstance(harness.provider, SecretsProvider)
    assert harness.provider.INTERFACE_VERSION == "1.1"


async def test_get_seeded_secret(harness: Harness) -> None:
    value = pysecrets.token_urlsafe(24)
    harness.seed("database", "api", "password", value)
    assert await harness.provider.get("secret://database/api#password") == value


async def test_get_map(harness: Harness) -> None:
    user, password = pysecrets.token_hex(8), pysecrets.token_hex(16)
    harness.seed("smtp", "relay", "user", user)
    harness.seed("smtp", "relay", "password", password)
    assert await harness.provider.get_map("secret://smtp/relay") == {"user": user, "password": password}


@pytest.mark.parametrize(
    "ref",
    [
        "secret://database/api#password",  # never seeded: no default value exists
        "secret://database/api#missing",
    ],
)
async def test_missing_secret_raises(harness: Harness, ref: str) -> None:
    with pytest.raises(SecretsUnavailableError):
        await harness.provider.get(ref)


async def test_missing_map_raises(harness: Harness) -> None:
    with pytest.raises(SecretsUnavailableError):
        await harness.provider.get_map("secret://nothing/here")


@pytest.mark.parametrize(
    "ref",
    [
        "database/password",
        "secret://database#password",
        "secret://../outside#key",
        "secret://database/../../outside#key",
        "secret://database/api#..",
        "secret://database/api#../../x",
    ],
)
async def test_malformed_or_traversing_refs_raise(harness: Harness, ref: str) -> None:
    with pytest.raises(SecretsUnavailableError):
        await harness.provider.get(ref)


async def test_put_then_get_map_round_trips(harness: Harness) -> None:
    values = {"token": pysecrets.token_hex(12), "signing_key": pysecrets.token_hex(12)}
    await harness.provider.put("secret://assetflow/orgs/org-a/channels/chan-1", values)
    assert await harness.provider.get_map("secret://assetflow/orgs/org-a/channels/chan-1") == values
    assert (
        await harness.provider.get("secret://assetflow/orgs/org-a/channels/chan-1#token") == values["token"]
    )


async def test_put_replaces_every_key(harness: Harness) -> None:
    path = "secret://assetflow/orgs/org-a/channels/chan-2"
    await harness.provider.put(path, {"old": "1", "kept": "2"})
    await harness.provider.put(path, {"kept": "3"})
    assert await harness.provider.get_map(path) == {"kept": "3"}


@pytest.mark.parametrize(
    "path",
    ["database/api", "secret://database", "secret://../outside/x", "secret://area/../../x", "secret://area/"],
)
async def test_put_refuses_malformed_or_traversing_paths(harness: Harness, path: str) -> None:
    with pytest.raises(SecretsUnavailableError):
        await harness.provider.put(path, {"key": "value"})


async def test_patch_changes_only_the_given_keys(harness: Harness) -> None:
    path = "secret://assetflow/orgs/org-a/channels/chan-3"
    await harness.provider.put(path, {"token": "one", "signing_key": "two"})
    await harness.provider.patch(path, {"token": "three"})
    assert await harness.provider.get_map(path) == {"token": "three", "signing_key": "two"}


async def test_patch_with_none_removes_that_key_only(harness: Harness) -> None:
    path = "secret://assetflow/orgs/org-a/channels/chan-4"
    await harness.provider.put(path, {"token": "one", "signing_key": "two"})
    await harness.provider.patch(path, {"signing_key": None})
    assert await harness.provider.get_map(path) == {"token": "one"}


async def test_patch_of_a_secret_that_does_not_exist_fails(harness: Harness) -> None:
    with pytest.raises(SecretsUnavailableError):
        await harness.provider.patch("secret://assetflow/orgs/org-a/channels/never-written", {"k": "v"})


@pytest.mark.parametrize("path", ["secret://area", "secret://area/../x", "x/y"])
async def test_patch_refuses_malformed_paths(harness: Harness, path: str) -> None:
    with pytest.raises(SecretsUnavailableError):
        await harness.provider.patch(path, {"k": "v"})


async def test_put_refuses_an_empty_secret(harness: Harness) -> None:
    with pytest.raises(SecretsUnavailableError):
        await harness.provider.put("secret://area/name", {})


async def test_a_provider_without_put_says_so() -> None:
    class ReadOnly(SecretsProvider):
        async def get(self, ref: str) -> str:
            return ""

        async def get_map(self, path: str) -> dict[str, str]:
            return {}

        async def encrypt(self, context: str, plaintext: str) -> str:
            return ""

        async def decrypt(self, context: str, ciphertext: str) -> str:
            return ""

        async def health(self) -> dict[str, object]:
            return {}

    with pytest.raises(NotImplementedError):
        await ReadOnly().put("secret://a/b", {"k": "v"})


async def test_encrypt_round_trip(harness: Harness) -> None:
    plaintext = pysecrets.token_urlsafe(32)
    ciphertext = await harness.provider.encrypt("org-a", plaintext)
    assert await harness.provider.decrypt("org-a", ciphertext) == plaintext


async def test_encrypt_uses_fresh_nonce(harness: Harness) -> None:
    first = await harness.provider.encrypt("org-a", "same")
    second = await harness.provider.encrypt("org-a", "same")
    assert first != second


async def test_ciphertext_hides_plaintext(harness: Harness) -> None:
    plaintext = "visible-marker-" + pysecrets.token_hex(8)
    ciphertext = await harness.provider.encrypt("org-a", plaintext)
    decoded = base64.b64decode(ciphertext.rsplit(":", 1)[-1])
    assert plaintext.encode() not in decoded
    assert plaintext not in ciphertext


async def test_wrong_context_fails_generically(harness: Harness) -> None:
    ciphertext = await harness.provider.encrypt("org-a", "value")
    with pytest.raises(SecretDecryptionError) as exc:
        await harness.provider.decrypt("org-b", ciphertext)
    assert "org-a" not in str(exc.value)
    assert "org-b" not in str(exc.value)


async def test_encrypt_many_round_trips_each_item_with_its_own_context(harness: Harness) -> None:
    items = [("asset:org-a:ssn", "123-45-6789"), ("asset:org-a:pin", "4321")]
    ciphertexts = await harness.provider.encrypt_many(items)
    assert len(ciphertexts) == len(items)
    for (context, plaintext), ciphertext in zip(items, ciphertexts, strict=True):
        assert await harness.provider.decrypt(context, ciphertext) == plaintext


async def test_encrypt_many_of_nothing_returns_nothing(harness: Harness) -> None:
    assert await harness.provider.encrypt_many([]) == []


async def test_encrypt_many_ciphertext_cannot_be_replayed_into_another_context(harness: Harness) -> None:
    (ciphertext,) = await harness.provider.encrypt_many([("asset:org-a:ssn", "value")])
    with pytest.raises(SecretDecryptionError):
        await harness.provider.decrypt("asset:org-a:pin", ciphertext)


async def test_default_encrypt_many_loops_over_encrypt(
    monkeypatch: pytest.MonkeyPatch, harness: Harness
) -> None:
    if type(harness.provider).encrypt_many is not SecretsProvider.encrypt_many:
        pytest.skip("this provider has its own batch path (covered by its own tests)")
    calls: list[tuple[str, str]] = []
    real_encrypt = harness.provider.encrypt

    async def spy_encrypt(context: str, plaintext: str) -> str:
        calls.append((context, plaintext))
        return await real_encrypt(context, plaintext)

    monkeypatch.setattr(harness.provider, "encrypt", spy_encrypt)
    items = [("ctx-1", "a"), ("ctx-2", "b")]
    await harness.provider.encrypt_many(items)
    assert calls == items


@pytest.mark.parametrize("mutate", ["flip", "truncate", "garbage", "prefix"])
async def test_tampered_ciphertext_fails(harness: Harness, mutate: str) -> None:
    ciphertext = await harness.provider.encrypt("org-a", "value")
    prefix, _, body = ciphertext.rpartition(":")
    raw = bytearray(base64.b64decode(body))
    if mutate == "flip":
        raw[-1] ^= 0x01
        bad = f"{prefix}:{base64.b64encode(bytes(raw)).decode()}"
    elif mutate == "truncate":
        bad = f"{prefix}:{base64.b64encode(bytes(raw[:10])).decode()}"
    elif mutate == "garbage":
        bad = f"{prefix}:!!!not-base64!!!"
    else:
        bad = "enc:v0:other:" + body
    with pytest.raises(SecretDecryptionError):
        await harness.provider.decrypt("org-a", bad)


async def test_health_reports_status_without_paths(harness: Harness, tmp_path: Path) -> None:
    health = await harness.provider.health()
    assert health["status"] in {"healthy", "degraded", "unhealthy"}
    rendered = repr(health)
    assert str(tmp_path) not in rendered
    assert tmp_path.name not in rendered


# ------------------------------------------------------------------------------ file specifics


async def test_file_json_layout(tmp_path: Path) -> None:
    value = pysecrets.token_hex(12)
    (tmp_path / "database").mkdir()
    (tmp_path / "database" / "worker.json").write_text(f'{{"password": "{value}"}}', encoding="utf-8")
    provider = FileSecretsProvider(ctx(tmp_path), tmp_path)
    assert await provider.get("secret://database/worker#password") == value


async def test_file_env_lookup_only_when_allowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    value = pysecrets.token_hex(12)
    monkeypatch.setenv("ASSETFLOW_SECRET_DATABASE_API_PASSWORD", value)
    denied = FileSecretsProvider(ctx(tmp_path), tmp_path)
    with pytest.raises(SecretsUnavailableError):
        await denied.get("secret://database/api#password")
    allowed = FileSecretsProvider(ctx(tmp_path), tmp_path, allow_env=True)
    assert await allowed.get("secret://database/api#password") == value


async def test_file_symlink_escape_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "area").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "key").write_text(pysecrets.token_hex(8), encoding="utf-8")
    try:
        (root / "area" / "name").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are not permitted on this machine")
    provider = FileSecretsProvider(ctx(tmp_path), root)
    with pytest.raises(SecretsUnavailableError):
        await provider.get("secret://area/name#key")


async def test_file_missing_key_file(tmp_path: Path) -> None:
    provider = FileSecretsProvider(ctx(tmp_path), tmp_path, encryption_key_file="transit/file.key")
    with pytest.raises(SecretsUnavailableError):
        await provider.encrypt("org-a", "value")
    assert (await provider.health())["status"] == "degraded"


async def test_file_key_outside_directory_is_refused(tmp_path: Path) -> None:
    (tmp_path / "outside.key").write_bytes(os.urandom(32))
    (tmp_path / "root").mkdir()
    provider = FileSecretsProvider(ctx(tmp_path), tmp_path / "root", encryption_key_file="../outside.key")
    with pytest.raises(SecretsUnavailableError):
        await provider.encrypt("org-a", "value")


@pytest.mark.parametrize("content", [b"short", base64.b64encode(os.urandom(16))])
async def test_file_wrong_key_length(tmp_path: Path, content: bytes) -> None:
    (tmp_path / "file.key").write_bytes(content)
    provider = FileSecretsProvider(ctx(tmp_path), tmp_path, encryption_key_file="file.key")
    with pytest.raises(SecretsUnavailableError):
        await provider.encrypt("org-a", "value")


async def test_file_accepts_raw_key(tmp_path: Path) -> None:
    (tmp_path / "file.key").write_bytes(os.urandom(32))
    provider = FileSecretsProvider(ctx(tmp_path), tmp_path, encryption_key_file="file.key")
    ciphertext = await provider.encrypt("org-a", "value")
    assert ciphertext.startswith(CIPHERTEXT_PREFIX)
    assert await provider.decrypt("org-a", ciphertext) == "value"


async def test_file_health_unhealthy_without_directory(tmp_path: Path) -> None:
    provider = FileSecretsProvider(ctx(tmp_path), tmp_path / "absent")
    assert (await provider.health())["status"] == "unhealthy"


def test_file_refused_in_production(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as exc:
        FileSecretsProvider.from_settings({"directory": str(tmp_path)}, ctx(tmp_path, "production"))
    assert exc.value.errors[0][0] == "providers.secrets.type"


def test_file_rejects_unknown_settings(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as exc:
        FileSecretsProvider.from_settings({"secrets_dir": "x"}, ctx(tmp_path))
    assert exc.value.errors[0][0] == "providers.secrets.settings.secrets_dir"


async def test_file_put_is_refused_in_production(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        FileSecretsProvider(ctx(tmp_path, env="production"), tmp_path)


# ------------------------------------------------------------------------------ openbao negatives


async def test_openbao_decrypt_with_another_orgs_context_fails_generically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _openbao_harness(tmp_path, monkeypatch).provider
    ciphertext = await provider.encrypt("org:org-a:asset:1:ssn", "123-45-6789")
    with pytest.raises(SecretDecryptionError) as exc:
        await provider.decrypt("org:org-b:asset:1:ssn", ciphertext)
    assert "org-a" not in str(exc.value)
    assert "org-b" not in str(exc.value)


async def test_openbao_sends_the_context_on_encrypt_and_decrypt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bao = FakeBao()
    bao.install(monkeypatch)
    provider = OpenBaoSecretsProvider.from_settings(
        {"address": "http://bao.test:8200", "token": "t-1"}, ctx(tmp_path)
    )
    ciphertext = await provider.encrypt("org-a", "v")
    await provider.decrypt("org-a", ciphertext)
    bodies = [json.loads(r.content) for r in bao.requests if "/transit/" in r.url.path]
    assert len(bodies) == 2
    assert all(b["context"] == base64.b64encode(b"org-a").decode() for b in bodies)


async def test_openbao_rejected_token_is_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    FakeBao().install(monkeypatch)
    provider = OpenBaoSecretsProvider.from_settings(
        {"address": "http://bao.test:8200", "token": "revoked"}, ctx(tmp_path)
    )
    with pytest.raises(SecretsUnavailableError):
        await provider.get_map("secret://database/api")
    with pytest.raises(SecretsUnavailableError):
        await provider.encrypt("org-a", "v")
