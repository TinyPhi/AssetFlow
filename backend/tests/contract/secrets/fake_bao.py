# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""An in-memory OpenBao for contract tests: KV v2, AppRole login, renew-self, derived transit.

The transit key behaves like a ``derived: true`` key: the per-context key is derived from the
master key and the request ``context``, so ciphertext only decrypts under the same context.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from typing import Any

import httpx
import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class FakeBao:
    def __init__(self) -> None:
        self.kv: dict[str, dict[str, str]] = {}
        self.requests: list[httpx.Request] = []
        self.valid_tokens: set[str] = {"t-1"}
        self.logins = 0
        self.renewals = 0
        self.lease_duration = 3600
        self.revoke_everything_after_each_call = False
        self._master = os.urandom(32)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        real = httpx.AsyncClient

        def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
            kwargs.pop("verify", None)
            return real(*args, transport=httpx.MockTransport(self.handle), **kwargs)

        monkeypatch.setattr("app.providers.secrets.openbao.httpx.AsyncClient", factory)

    # ---------------------------------------------------------------- transit
    def _aead(self, context_b64: str) -> AESGCM:
        key = hmac.new(self._master, base64.b64decode(context_b64), hashlib.sha256).digest()
        return AESGCM(key)

    def _encrypt(self, plaintext_b64: str, context_b64: str) -> str:
        nonce = os.urandom(12)
        sealed = self._aead(context_b64).encrypt(nonce, base64.b64decode(plaintext_b64), None)
        return "vault:v1:" + base64.b64encode(nonce + sealed).decode()

    def _decrypt(self, ciphertext: str, context_b64: str) -> str | None:
        if not ciphertext.startswith("vault:v1:"):
            return None
        try:
            raw = base64.b64decode(ciphertext.removeprefix("vault:v1:"), validate=True)
            plain = self._aead(context_b64).decrypt(raw[:12], raw[12:], None)
        except (ValueError, InvalidTag):
            return None
        return base64.b64encode(plain).decode()

    # ---------------------------------------------------------------- handler
    def handle(self, request: httpx.Request) -> httpx.Response:
        response = self._route(request)
        if self.revoke_everything_after_each_call:
            self.valid_tokens.clear()
        return response

    def _route(self, request: httpx.Request) -> httpx.Response:  # noqa: PLR0911
        self.requests.append(request)
        path = request.url.path.removeprefix("/v1/")
        if path == "sys/health":
            return httpx.Response(200, json={"initialized": True, "sealed": False})
        if path == "auth/approle/login":
            self.logins += 1
            token = f"t-login-{self.logins}"
            self.valid_tokens.add(token)
            return httpx.Response(
                200, json={"auth": {"client_token": token, "lease_duration": self.lease_duration}}
            )
        if request.headers.get("x-vault-token") not in self.valid_tokens:
            return httpx.Response(403, json={"errors": ["permission denied"]})
        if path == "auth/token/renew-self":
            self.renewals += 1
            return httpx.Response(200, json={"auth": {"lease_duration": self.lease_duration}})
        body: dict[str, Any] = json.loads(request.content) if request.content else {}
        if path.startswith("secret/data/"):
            return self._kv(request.method, path.removeprefix("secret/data/"), body)
        if path.startswith("transit/encrypt/"):
            return self._transit_encrypt(body)
        if path.startswith("transit/decrypt/"):
            return self._transit_decrypt(body)
        return httpx.Response(404, json={"errors": []})

    def _kv(self, method: str, name: str, body: dict[str, Any]) -> httpx.Response:
        if method == "GET":
            if name not in self.kv:
                return httpx.Response(404, json={"errors": []})
            return httpx.Response(200, json={"data": {"data": self.kv[name]}})
        data: dict[str, Any] = body.get("data", {})
        if method == "POST":
            self.kv[name] = {k: str(v) for k, v in data.items()}
        elif method == "PATCH":
            if name not in self.kv:
                return httpx.Response(404, json={"errors": []})
            merged: dict[str, str] = {**self.kv[name]}
            for key, value in data.items():
                if value is None:
                    merged.pop(key, None)
                else:
                    merged[key] = str(value)
            self.kv[name] = merged
        return httpx.Response(200, json={"data": {"version": 1}})

    def _transit_encrypt(self, body: dict[str, Any]) -> httpx.Response:
        if "batch_input" in body:
            results = [
                {"ciphertext": self._encrypt(i["plaintext"], i["context"])} for i in body["batch_input"]
            ]
            return httpx.Response(200, json={"data": {"batch_results": results}})
        if "context" not in body:  # a derived key refuses a request without context
            return httpx.Response(400, json={"errors": ["missing derivation context"]})
        return httpx.Response(
            200, json={"data": {"ciphertext": self._encrypt(body["plaintext"], body["context"])}}
        )

    def _transit_decrypt(self, body: dict[str, Any]) -> httpx.Response:
        if "context" not in body:
            return httpx.Response(400, json={"errors": ["missing derivation context"]})
        plain = self._decrypt(body["ciphertext"], body["context"])
        if plain is None:
            return httpx.Response(400, json={"errors": ["cipher: message authentication failed"]})
        return httpx.Response(200, json={"data": {"plaintext": plain}})
