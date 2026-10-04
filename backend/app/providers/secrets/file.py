# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""``file`` secrets provider: the dev/CI fallback (§B6.2, decision 51). Refused in production.

Layout under ``settings.directory`` (Docker/Kubernetes secrets style, default ``/run/secrets``)::

    <area>/<name>/<key>      one file per key (plain text, trailing newline ignored), or
    <area>/<name>.json       a JSON object of keys

``secret://database/api#password`` reads ``database/api/password`` or key ``password`` of
``database/api.json``. With ``allow_env: true`` it also reads the environment variable
``ASSETFLOW_SECRET_DATABASE_API_PASSWORD``. A missing secret raises ``SecretsUnavailableError``:
there are no default values. Every path is resolved and must stay inside the directory.

Field encryption is AES-256-GCM with a 32-byte key read from ``encryption_key_file`` (raw bytes
or base64, relative to the directory). Each call uses a fresh 96-bit nonce and binds ``context``
as associated data. Output: ``enc:v1:file:<base64(nonce || ciphertext || tag)>``.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import SECRET_REF_PATTERN, is_secret_ref
from app.core.problems import SecretsUnavailableError
from app.providers.context import ProviderContext, ProviderSettings, parse_settings, refuse_in_production
from app.providers.secrets.base import SecretDecryptionError, SecretsProvider

logger = logging.getLogger(__name__)

CIPHERTEXT_PREFIX = "enc:v1:file:"
_KEY_BYTES = 32
_NONCE_BYTES = 12
_TAG_BYTES = 16
_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
_MAP_REF_PATTERN = re.compile(
    r"^secret://(?P<area>[A-Za-z0-9_-]+)/(?P<name>[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)$"
)


class FileSecretsSettings(ProviderSettings):
    """``providers.secrets.settings`` for ``type: file``."""

    directory: str = "/run/secrets"
    encryption_key_file: str | None = None
    allow_env: bool = False


def env_var_name(area: str, name: str, key: str) -> str:
    """``secret://database/api#password`` -> ``ASSETFLOW_SECRET_DATABASE_API_PASSWORD``."""
    raw = "_".join((area, name, key))
    return "ASSETFLOW_SECRET_" + re.sub(r"[^A-Za-z0-9]", "_", raw).upper()


class FileSecretsProvider(SecretsProvider):
    """Reads secrets from a directory; encrypts with a local AES-256-GCM key."""

    def __init__(
        self,
        context: ProviderContext,
        directory: str | Path,
        *,
        encryption_key_file: str | None = None,
        allow_env: bool = False,
    ) -> None:
        refuse_in_production(context, "file secrets")
        root = Path(directory)
        self._root = (root if root.is_absolute() else context.base_dir / root).resolve()
        self._key_file = encryption_key_file
        self._allow_env = allow_env
        self._key: bytes | None = None

    @classmethod
    def from_settings(cls, settings: dict[str, Any], context: ProviderContext) -> FileSecretsProvider:
        """Registry factory."""
        parsed = parse_settings(FileSecretsSettings, settings, context)
        return cls(
            context,
            parsed.directory,
            encryption_key_file=parsed.encryption_key_file,
            allow_env=parsed.allow_env,
        )

    # ------------------------------------------------------------------------------------ reads

    async def get(self, ref: str) -> str:
        """Return one secret value or raise ``SecretsUnavailableError``."""
        match = SECRET_REF_PATTERN.match(ref)
        if match is None or not is_secret_ref(ref):
            raise SecretsUnavailableError("A secret reference is malformed.")
        area, name, key = match.group("area"), match.group("name"), match.group("key")
        value = await asyncio.to_thread(self._read_key, area, name, key)
        if value is None and self._allow_env:
            value = os.environ.get(env_var_name(area, name, key))
        if value is None:
            logger.warning("secrets.file.missing", extra={"secret_ref": ref})
            raise SecretsUnavailableError("A required secret is not available.")
        return value

    async def get_map(self, path: str) -> dict[str, str]:
        """Return every key of ``secret://<area>/<name>``."""
        match = _MAP_REF_PATTERN.match(path)
        if match is None or any(seg in {".", ".."} for seg in path[len("secret://") :].split("/")):
            raise SecretsUnavailableError("A secret reference is malformed.")
        values = await asyncio.to_thread(self._read_map, match.group("area"), match.group("name"))
        if not values:
            logger.warning("secrets.file.missing", extra={"secret_ref": path})
            raise SecretsUnavailableError("A required secret is not available.")
        return values

    async def put(self, path: str, values: Mapping[str, str]) -> None:
        """Replace every key of ``secret://<area>/<name>`` (dev/CI only; production is refused)."""
        match = _MAP_REF_PATTERN.match(path)
        if match is None or any(seg in {".", ".."} for seg in path[len("secret://") :].split("/")):
            raise SecretsUnavailableError("A secret reference is malformed.")
        if not values or not all(_KEY_PATTERN.match(k) and isinstance(v, str) for k, v in values.items()):
            raise SecretsUnavailableError("A secret needs at least one key with a text value.")
        await asyncio.to_thread(self._write_map, match.group("area"), match.group("name"), dict(values))

    async def patch(self, path: str, values: Mapping[str, str | None]) -> None:
        """Change only the given keys of an existing secret; ``None`` removes a key."""
        match = _MAP_REF_PATTERN.match(path)
        if match is None or any(seg in {".", ".."} for seg in path[len("secret://") :].split("/")):
            raise SecretsUnavailableError("A secret reference is malformed.")
        valid = all(_KEY_PATTERN.match(k) and (v is None or isinstance(v, str)) for k, v in values.items())
        if not values or not valid:
            raise SecretsUnavailableError("A secret patch needs at least one key with a text value or null.")
        current = await asyncio.to_thread(self._read_map, match.group("area"), match.group("name"))
        if not current:
            raise SecretsUnavailableError("A required secret is not available.")
        merged = {**current, **{k: v for k, v in values.items() if v is not None}}
        for key, value in values.items():
            if value is None:
                merged.pop(key, None)
        await asyncio.to_thread(self._write_map, match.group("area"), match.group("name"), merged)

    def _write_map(self, area: str, name: str, values: dict[str, str]) -> None:
        folder = self._inside(area, name)
        if folder is None:
            raise SecretsUnavailableError("A secret reference is malformed.")
        try:
            folder.mkdir(parents=True, exist_ok=True)
            for stale in folder.iterdir():
                if stale.is_file() and stale.name not in values:
                    stale.unlink()
            for key, value in values.items():
                target = folder / key
                target.write_text(value, encoding="utf-8")
                target.chmod(0o600)
        except OSError as exc:
            raise SecretsUnavailableError("A secrets file cannot be written.") from exc

    def _inside(self, *parts: str) -> Path | None:
        """Resolve ``parts`` under the root; None when the result escapes the root."""
        candidate = self._root.joinpath(*parts).resolve()
        return candidate if candidate.is_relative_to(self._root) else None

    def _read_key(self, area: str, name: str, key: str) -> str | None:
        single = self._inside(area, name, key)
        if single is not None and single.is_file():
            return self._read_text(single)
        return self._read_json(area, name).get(key)

    def _read_map(self, area: str, name: str) -> dict[str, str]:
        values = self._read_json(area, name)
        folder = self._inside(area, name)
        if folder is not None and folder.is_dir():
            for entry in sorted(folder.iterdir()):
                if entry.is_file() and entry.resolve().is_relative_to(self._root):
                    values[entry.name] = self._read_text(entry)
        return values

    def _read_json(self, area: str, name: str) -> dict[str, str]:
        json_file = self._inside(area, f"{name}.json")
        if json_file is None or not json_file.is_file():
            return {}
        try:
            data = json.loads(self._read_text(json_file))
        except ValueError as exc:
            raise SecretsUnavailableError("A secrets file is not valid JSON.") from exc
        if not isinstance(data, dict):
            raise SecretsUnavailableError("A secrets file must hold a JSON object.")
        return {str(k): str(v) for k, v in data.items() if isinstance(v, str | int | float | bool)}

    @staticmethod
    def _read_text(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8").rstrip("\r\n")
        except (OSError, UnicodeDecodeError) as exc:
            raise SecretsUnavailableError("A secrets file cannot be read.") from exc

    # ------------------------------------------------------------------------------- encryption

    def _load_key(self) -> bytes:
        if self._key is not None:
            return self._key
        key_path = self._inside(self._key_file) if self._key_file else None
        if key_path is None or not key_path.is_file():
            raise SecretsUnavailableError("The field-encryption key is not available.")
        try:
            raw = key_path.read_bytes()
        except OSError as exc:
            raise SecretsUnavailableError("The field-encryption key cannot be read.") from exc
        key = raw if len(raw) == _KEY_BYTES else _decode_b64_key(raw)
        if key is None:
            raise SecretsUnavailableError("The field-encryption key must be 32 bytes (raw or base64).")
        self._key = key
        return key

    async def encrypt(self, context: str, plaintext: str) -> str:
        """AES-256-GCM with a random nonce; ``context`` is the associated data."""
        key = await asyncio.to_thread(self._load_key)
        nonce = os.urandom(_NONCE_BYTES)
        sealed = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), context.encode("utf-8"))
        return CIPHERTEXT_PREFIX + base64.b64encode(nonce + sealed).decode("ascii")

    async def decrypt(self, context: str, ciphertext: str) -> str:
        """Reverse :meth:`encrypt`; any failure raises the generic ``SecretDecryptionError``."""
        key = await asyncio.to_thread(self._load_key)
        if not ciphertext.startswith(CIPHERTEXT_PREFIX):
            raise SecretDecryptionError
        try:
            blob = base64.b64decode(ciphertext[len(CIPHERTEXT_PREFIX) :], validate=True)
        except (binascii.Error, ValueError) as exc:
            raise SecretDecryptionError from exc
        if len(blob) < _NONCE_BYTES + _TAG_BYTES:
            raise SecretDecryptionError
        nonce, sealed = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
        try:
            return AESGCM(key).decrypt(nonce, sealed, context.encode("utf-8")).decode("utf-8")
        except (InvalidTag, UnicodeDecodeError) as exc:
            raise SecretDecryptionError from exc

    # ----------------------------------------------------------------------------------- health

    async def health(self) -> dict[str, Any]:
        """Directory present and key usable; never reports paths or values."""
        directory_ok = await asyncio.to_thread(self._root.is_dir)
        encryption = "not configured"
        if self._key_file:
            try:
                await asyncio.to_thread(self._load_key)
                encryption = "ready"
            except SecretsUnavailableError:
                encryption = "unavailable"
        status = "healthy" if directory_ok else "unhealthy"
        if directory_ok and encryption == "unavailable":
            status = "degraded"
        return {
            "status": status,
            "provider": "file",
            "directory_present": directory_ok,
            "encryption": encryption,
        }


def _decode_b64_key(raw: bytes) -> bytes | None:
    try:
        key = base64.b64decode(raw.strip(), validate=True)
    except (binascii.Error, ValueError):
        return None
    return key if len(key) == _KEY_BYTES else None
