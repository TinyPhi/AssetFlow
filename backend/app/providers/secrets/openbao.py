# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""OpenBao secrets provider (§B6.2, §B11.4, M1.3-T9).

Supports KV v2 secrets retrieval, transit engine encryption/decryption,
and AppRole authentication.
"""

from __future__ import annotations

import base64
import logging
import os
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx

from app.core.config import ConfigError, is_secret_ref, parse_secret_ref
from app.core.problems import SecretsUnavailableError
from app.providers.context import ProviderContext, ProviderSettings, parse_settings
from app.providers.secrets.base import SecretDecryptionError, SecretsProvider

logger = logging.getLogger(__name__)


class OpenBaoSettings(ProviderSettings):
    """``providers.secrets.settings`` for ``type: openbao``."""

    address: str = "http://localhost:19200"
    role_id: str | None = None
    secret_id_file: str | None = None
    token: str | None = None
    mount_point: str = "secret"
    transit_mount: str = "transit"
    transit_key: str = "assetflow-fields"
    ca_cert: str | None = None  # CA bundle for a private TLS chain; falls back to BAO_CACERT


class OpenBaoSecretsProvider(SecretsProvider):
    """Production SecretsProvider connecting to OpenBao / Vault API (§B6.2)."""

    def __init__(self, settings: OpenBaoSettings, context: ProviderContext) -> None:
        self.settings = settings
        self.context = context
        self._token = settings.token
        self._token_expires_at: float | None = None  # monotonic; None = unknown or static token
        self._token_ttl = 0.0
        self._can_login = bool(settings.role_id and settings.secret_id_file)

        if context.env == "production":
            errors: list[tuple[str, str]] = []
            if not settings.address.startswith("https://"):
                errors.append(("providers.secrets.settings.address", "address must use HTTPS in production"))
            if not self._token and not (settings.role_id and settings.secret_id_file):
                errors.append(
                    (
                        "providers.secrets.settings",
                        "either token or role_id with secret_id_file is required in production",
                    )
                )
            if errors:
                raise ConfigError(errors)

    @classmethod
    def from_settings(cls, settings: dict[str, Any], context: ProviderContext) -> OpenBaoSecretsProvider:
        """Registry factory."""
        parsed = parse_settings(OpenBaoSettings, settings, context)
        return cls(parsed, context)

    def _client(self, timeout: float = 10.0) -> httpx.AsyncClient:
        """HTTP client verifying TLS against ``ca_cert`` / ``BAO_CACERT`` when set."""
        ca = self.settings.ca_cert or os.environ.get("BAO_CACERT") or None
        if ca:
            path = Path(ca)
            if not path.is_absolute():
                path = self.context.base_dir / path
            return httpx.AsyncClient(timeout=timeout, verify=str(path))
        return httpx.AsyncClient(timeout=timeout)

    def _url(self, path: str) -> str:
        return f"{self.settings.address.rstrip('/')}/v1/{path}"

    def _track(self, auth: object) -> None:
        """Remember when the AppRole token expires, from the login or renew response."""
        ttl = auth.get("lease_duration") if isinstance(auth, dict) else None
        if isinstance(ttl, int | float) and ttl > 0:
            self._token_ttl = float(ttl)
            self._token_expires_at = time.monotonic() + float(ttl)
        else:
            self._token_expires_at = None

    async def _login(self, client: httpx.AsyncClient) -> str:
        """Fresh AppRole login."""
        if not (self._can_login and self.settings.secret_id_file):
            raise SecretsUnavailableError("No OpenBao authentication credentials available.")
        path = Path(self.settings.secret_id_file)
        if not path.is_absolute():
            path = self.context.base_dir / path
        if not path.exists():
            raise SecretsUnavailableError("OpenBao secret_id_file not found.")
        secret_id = path.read_text(encoding="utf-8").strip()
        try:
            res = await client.post(
                self._url("auth/approle/login"),
                json={"role_id": self.settings.role_id, "secret_id": secret_id},
            )
            if res.status_code == 200:
                auth = res.json().get("auth", {})
                token = auth.get("client_token")
                if isinstance(token, str) and token:
                    self._token = token
                    self._track(auth)
                    return token
        except Exception as exc:
            raise SecretsUnavailableError(f"Failed to authenticate with OpenBao AppRole: {exc}") from exc
        raise SecretsUnavailableError("OpenBao AppRole login was refused.")

    async def _renew(self, client: httpx.AsyncClient) -> bool:
        """``renew-self`` the current token; False when it could not be renewed."""
        try:
            res = await client.post(
                self._url("auth/token/renew-self"), headers={"X-Vault-Token": self._token or ""}
            )
            if res.status_code == 200:
                auth = res.json().get("auth", {})
                self._track(auth)
                return True
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("OpenBao renew-self request failed: %s", type(exc).__name__)
        return False

    async def _ensure_token(self, client: httpx.AsyncClient) -> str:
        """Return a usable token: login if none, renew-self once past 2/3 of its lease."""
        if not self._token:
            return await self._login(client)
        if self._token_expires_at is not None:
            remaining = self._token_expires_at - time.monotonic()
            if remaining <= self._token_ttl / 3 and not await self._renew(client):
                if self._can_login:
                    return await self._login(client)
                if remaining <= 0:
                    raise SecretsUnavailableError("OpenBao token expired.")
        return self._token

    async def _send(self, client: httpx.AsyncClient, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Authenticated request; on 403 log in afresh once and retry (token revoked or expired)."""
        headers = dict(kwargs.pop("headers", None) or {})
        token = await self._ensure_token(client)
        res = await client.request(method, url, headers={**headers, "X-Vault-Token": token}, **kwargs)
        if res.status_code == 403 and self._can_login:
            self._token = None
            token = await self._login(client)
            res = await client.request(method, url, headers={**headers, "X-Vault-Token": token}, **kwargs)
        return res

    async def get(self, ref: str) -> str:
        """Fetch secret value by reference `secret://<area>/<name>#<key>`."""
        if not is_secret_ref(ref):
            raise SecretsUnavailableError(f"Invalid secret reference format: {ref!r}")

        area, name, key = parse_secret_ref(ref)
        values = await self.get_map(f"secret://{area}/{name}")
        if key not in values:
            raise SecretsUnavailableError(f"Secret key {key!r} not found in secret://{area}/{name}")
        return values[key]

    async def get_map(self, path: str) -> dict[str, str]:
        """Fetch all key-value pairs for `secret://<area>/<name>`."""
        area, name = self._split_path(path)
        url = f"{self.settings.address.rstrip('/')}/v1/{self.settings.mount_point}/data/{area}/{name}"

        async with self._client() as client:
            try:
                res = await self._send(client, "GET", url)
                if res.status_code == 404:
                    raise SecretsUnavailableError(f"Secret {area}/{name} not found.")
                if res.status_code != 200:
                    raise SecretsUnavailableError("OpenBao returned non-200 status.")
                raw_data = res.json().get("data", {}).get("data", {})
                return {str(k): str(v) for k, v in raw_data.items()}
            except Exception as exc:
                if isinstance(exc, SecretsUnavailableError):
                    raise
                raise SecretsUnavailableError(f"OpenBao KV read error: {exc}") from exc

    @staticmethod
    def _split_path(path: str) -> tuple[str, str]:
        """``secret://<area>/<name>``; ``name`` may hold more segments, none empty or dot-only."""
        prefix = "secret://"
        if not path.startswith(prefix):
            raise SecretsUnavailableError(f"Malformed path {path!r}; expected secret://<area>/<name>")
        parts = path[len(prefix) :].split("#", maxsplit=1)[0].split("/")
        if len(parts) < 2 or any(not p or p in {".", ".."} for p in parts):
            raise SecretsUnavailableError(f"Malformed path {path!r}; expected secret://<area>/<name>")
        return parts[0], "/".join(parts[1:])

    async def put(self, path: str, values: Mapping[str, str]) -> None:
        """Write a KV v2 secret, replacing all its keys (the api role has write-only access)."""
        area, name = self._split_path(path)
        if not values:
            raise SecretsUnavailableError("A secret needs at least one key.")
        url = f"{self.settings.address.rstrip('/')}/v1/{self.settings.mount_point}/data/{area}/{name}"
        async with self._client() as client:
            try:
                res = await self._send(client, "POST", url, json={"data": dict(values)})
            except httpx.HTTPError as exc:
                raise SecretsUnavailableError("OpenBao KV write error.") from exc
            if res.status_code not in (200, 204):
                raise SecretsUnavailableError("OpenBao refused the secret write.")

    async def patch(self, path: str, values: Mapping[str, str | None]) -> None:
        """KV v2 merge-patch: only the given keys change, a ``None`` removes its key."""
        area, name = self._split_path(path)
        if not values:
            raise SecretsUnavailableError("A secret patch needs at least one key.")
        url = f"{self.settings.address.rstrip('/')}/v1/{self.settings.mount_point}/data/{area}/{name}"
        async with self._client() as client:
            try:
                res = await self._send(
                    client,
                    "PATCH",
                    url,
                    headers={"Content-Type": "application/merge-patch+json"},
                    json={"data": dict(values)},
                )
            except httpx.HTTPError as exc:
                raise SecretsUnavailableError("OpenBao KV patch error.") from exc
            if res.status_code not in (200, 204):
                raise SecretsUnavailableError("OpenBao refused the secret patch.")

    async def encrypt(self, context: str, plaintext: str) -> str:
        """Encrypt `plaintext` bound to `context` using transit engine."""
        url = (
            f"{self.settings.address.rstrip('/')}/v1/"
            f"{self.settings.transit_mount}/encrypt/{self.settings.transit_key}"
        )
        pt_b64 = base64.b64encode(plaintext.encode("utf-8")).decode("ascii")
        ctx_b64 = base64.b64encode(context.encode("utf-8")).decode("ascii")

        async with self._client() as client:
            try:
                res = await self._send(client, "POST", url, json={"plaintext": pt_b64, "context": ctx_b64})
                if res.status_code != 200:
                    raise SecretsUnavailableError("OpenBao transit encryption failed.")
                data = res.json().get("data", {})
                ciphertext = data.get("ciphertext")
                if not isinstance(ciphertext, str):
                    raise SecretsUnavailableError("OpenBao transit did not return ciphertext.")
                return ciphertext
            except Exception as exc:
                if isinstance(exc, SecretsUnavailableError):
                    raise
                raise SecretsUnavailableError(f"OpenBao encryption error: {exc}") from exc

    async def encrypt_many(self, items: Sequence[tuple[str, str]]) -> list[str]:
        """Encrypt many `(context, plaintext)` pairs with transit's `batch_input` (one round trip)."""
        if not items:
            return []
        batch_input = [
            {
                "plaintext": base64.b64encode(plaintext.encode("utf-8")).decode("ascii"),
                "context": base64.b64encode(context.encode("utf-8")).decode("ascii"),
            }
            for context, plaintext in items
        ]
        url = (
            f"{self.settings.address.rstrip('/')}/v1/"
            f"{self.settings.transit_mount}/encrypt/{self.settings.transit_key}"
        )
        async with self._client() as client:
            try:
                res = await self._send(client, "POST", url, json={"batch_input": batch_input})
                if res.status_code != 200:
                    raise SecretsUnavailableError("OpenBao transit batch encryption failed.")
                results = res.json().get("data", {}).get("batch_results")
                if not isinstance(results, list) or len(results) != len(items):
                    raise SecretsUnavailableError("OpenBao transit batch result count mismatch.")
                ciphertexts: list[str] = []
                for result in results:
                    ciphertext = result.get("ciphertext") if isinstance(result, dict) else None
                    if not isinstance(ciphertext, str):
                        raise SecretsUnavailableError("OpenBao transit batch item failed.")
                    ciphertexts.append(ciphertext)
                return ciphertexts
            except Exception as exc:
                if isinstance(exc, SecretsUnavailableError):
                    raise
                raise SecretsUnavailableError(f"OpenBao batch encryption error: {exc}") from exc

    async def decrypt(self, context: str, ciphertext: str) -> str:
        """Decrypt `ciphertext` bound to `context` using transit engine."""
        url = (
            f"{self.settings.address.rstrip('/')}/v1/"
            f"{self.settings.transit_mount}/decrypt/{self.settings.transit_key}"
        )
        ctx_b64 = base64.b64encode(context.encode("utf-8")).decode("ascii")

        async with self._client() as client:
            try:
                res = await self._send(
                    client, "POST", url, json={"ciphertext": ciphertext, "context": ctx_b64}
                )
                if res.status_code != 200:
                    raise SecretDecryptionError()
                data = res.json().get("data", {})
                pt_b64 = data.get("plaintext")
                if not isinstance(pt_b64, str):
                    raise SecretDecryptionError()
                return base64.b64decode(pt_b64.encode("ascii")).decode("utf-8")
            except SecretDecryptionError:
                raise
            except Exception as exc:
                logger.warning("Decryption failed: %s", exc)
                raise SecretDecryptionError() from exc

    async def health(self) -> dict[str, Any]:
        """Return health status without exposing sensitive tokens or addresses."""
        health_url = f"{self.settings.address.rstrip('/')}/v1/sys/health"
        try:
            async with self._client(5.0) as client:
                res = await client.get(health_url)
                # 200 = initialized, unsealed, and active
                # 429 = unsealed and standby
                # 501 = not initialized
                # 503 = sealed
                status = "healthy" if res.status_code in (200, 429) else "unhealthy"
                return {
                    "status": status,
                    "provider": "openbao",
                    "sealed": res.status_code == 503,
                }
        except httpx.HTTPError as exc:
            logger.warning("OpenBao health check failed: %s", exc)
            return {"status": "unhealthy", "provider": "openbao", "error": "unreachable"}
