# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""SecretsProvider contract suite (§B6.1 rule 2) plus ``file``-specific checks.

Every secrets implementation is added to IMPLEMENTATIONS with a way to seed values. All secret
values here are random, generated at test time.
"""

from __future__ import annotations

import base64
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


def ctx(base_dir: Path, env: str = "test") -> ProviderContext:
    return ProviderContext(env=env, pillar="secrets", base_dir=base_dir)  # type: ignore[arg-type]


@dataclass
class Harness:
    provider: SecretsProvider
    seed: Callable[[str, str, str, str], None]  # area, name, key, value


def _file_harness(tmp_path: Path) -> Harness:
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


IMPLEMENTATIONS: list[tuple[str, Callable[[Path], Harness]]] = [("file", _file_harness)]


@pytest.fixture(params=IMPLEMENTATIONS, ids=[i[0] for i in IMPLEMENTATIONS])
def harness(request: pytest.FixtureRequest, tmp_path: Path) -> Harness:
    factory: Callable[[Path], Harness] = request.param[1]
    return factory(tmp_path)


# ------------------------------------------------------------------------------ shared contract


async def test_interface_version(harness: Harness) -> None:
    assert isinstance(harness.provider, SecretsProvider)
    assert harness.provider.INTERFACE_VERSION == "1.0"


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
