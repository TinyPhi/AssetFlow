# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""BFF Session flow E2E tests (§B11.2, M1.6-T2; AF-025, NEW-1, NEW-2).

The real app factory and routes run over httpx's ASGI transport. The ``mock`` provider stands in for
the IdP; the sign-in success path runs against a real PostgreSQL database, the failure paths need no
database because they stop before it.
"""

from __future__ import annotations

import base64
import json
import secrets
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from pg_harness import PoolFactory

from app.api.auth import AUTH_REFRESH_LIMIT, AUTH_SESSION_LIMIT, REFRESH_COOKIE_NAME
from app.core.cookie_crypto import derive_key
from app.core.db import Pool, tenant_transaction
from app.main import create_app
from app.providers.auth.mock import MockAuthProvider
from app.providers.context import ProviderContext

STATE_LEN = 32
ORIGIN = "http://localhost:5173"
OTHER_ORIGIN = "https://evil.example"
MARKER = {"X-Requested-With": "AssetFlow"}


def _pkce(**overrides: str) -> dict[str, str]:
    """A well-formed session exchange body with generated values; ``overrides`` replace fields."""
    body = {
        "code": f"code-{secrets.token_hex(8)}",
        "code_verifier": secrets.token_urlsafe(48),
        "state": secrets.token_urlsafe(STATE_LEN),
        "nonce": secrets.token_urlsafe(STATE_LEN),
        "redirect_uri": "/auth/callback",
    }
    body.update(overrides)
    return body


def _id_token(nonce: str) -> str:
    def part(data: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

    return f"{part({'alg': 'none'})}.{part({'nonce': nonce})}.sig"


class ClaimsAuth(MockAuthProvider):
    """Mock IdP whose exchanged access token verifies (JSON claims) and may carry an id_token."""

    def __init__(self, idp_org: str = "idp-none", id_token_nonce: str | None = None) -> None:
        super().__init__(ProviderContext("development", "auth", Path()))
        self.idp_org = idp_org
        self.id_token_nonce = id_token_nonce

    async def exchange_code(
        self, code: str, redirect_uri: str, code_verifier: str | None = None
    ) -> dict[str, Any]:
        tokens = self._issue()
        tokens["access_token"] = json.dumps(
            {
                "sub": f"sub-{uuid4().hex}",
                "organization_id": self.idp_org,
                "roles": ["admin"],
                "email": "a@e2e.test",
            }
        )
        if self.id_token_nonce is not None:
            tokens["id_token"] = _id_token(self.id_token_nonce)
        return tokens


class Registry:
    def __init__(self, auth: Any) -> None:
        self.auth = auth

    async def resolve_secret(self, ref: str) -> str:
        return "dummy-secret"


class DoublePool:
    """Enough pool for paths that must fail before the database is used."""

    async def execute(self, *args: Any, **kwargs: Any) -> None:
        pass


def _app(auth: Any, pool: Any, *, env: str = "development", cookie_key: bytes | None = None) -> FastAPI:
    app = create_app()
    app.state.config = type(
        "Config", (), {"env": env, "platform": type("Platform", (), {"allowed_origins": [ORIGIN]})()}
    )()
    app.state.registry = Registry(auth)
    app.state.pool = pool
    app.state.session_cookie_key = cookie_key if cookie_key is not None else derive_key(secrets.token_hex(16))
    return app


def _client(app: FastAPI, headers: dict[str, str] | None = None) -> httpx.AsyncClient:
    """A client that, like the SPA in a browser, sends the allowed Origin and the marker header."""
    default = {"Origin": ORIGIN, **MARKER} if headers is None else headers
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
        headers=default,
    )


async def _create_org(pool: Pool) -> str:
    org_id, idp_org = uuid4(), f"idp-{uuid4().hex[:12]}"
    settings = {"provisioning": "require_role"}
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.organizations"
            " (id, slug, name, idp_organization_id, domain_key, settings, status)"
            " VALUES ($1, $2, 'Session Org', $3, 'generic', $4::jsonb, 'active')",
            org_id,
            f"sess-{org_id.hex[:12]}",
            idp_org,
            json.dumps(settings),
        )
    return idp_org


@pytest.fixture
def anonymous_app() -> FastAPI:
    """An app whose IdP issues opaque (unverifiable) tokens, as the plain mock provider does."""
    return _app(MockAuthProvider(ProviderContext("development", "auth", Path())), DoublePool())


@pytest.fixture
async def db_client(make_pool: PoolFactory) -> AsyncIterator[tuple[httpx.AsyncClient, FastAPI, str]]:
    pool = await make_pool("api")
    idp_org = await _create_org(pool)
    app = _app(ClaimsAuth(idp_org), pool)
    async with _client(app) as client:
        yield client, app, idp_org


async def test_public_config_endpoint(anonymous_app: FastAPI) -> None:
    async with _client(anonymous_app) as client:
        res = await client.get("/api/config/public")
        assert res.status_code == 200
        data = res.json()
        assert "auth_mode" in data
        assert "client_id" in data
        assert "redirect_uri" in data
        assert "idle_timeout_minutes" in data


async def test_session_exchange_and_refresh_rotation(
    db_client: tuple[httpx.AsyncClient, FastAPI, str],
) -> None:
    client, _, _ = db_client
    res = await client.post("/api/auth/session", json=_pkce())
    assert res.status_code == 200
    body = res.json()
    assert "access_token" in body
    assert "expires_in" in body
    first_refresh_cookie = res.cookies[REFRESH_COOKIE_NAME]
    set_cookie = res.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=strict" in set_cookie
    assert "path=/api/auth" in set_cookie

    client.cookies.set(REFRESH_COOKIE_NAME, first_refresh_cookie)
    res2 = await client.post("/api/auth/refresh")
    assert res2.status_code == 200
    second_refresh_cookie = res2.cookies[REFRESH_COOKIE_NAME]
    assert first_refresh_cookie != second_refresh_cookie

    client.cookies.set(REFRESH_COOKIE_NAME, first_refresh_cookie)
    assert (await client.post("/api/auth/refresh")).status_code == 401

    client.cookies.set(REFRESH_COOKIE_NAME, second_refresh_cookie)
    assert (await client.post("/api/auth/logout")).status_code == 200


async def test_exchange_with_unverifiable_token_fails_closed(anonymous_app: FastAPI) -> None:
    """NEW-2: no verified principal means 401, no cookie and no token in the body."""
    async with _client(anonymous_app) as client:
        res = await client.post("/api/auth/session", json=_pkce())
    assert res.status_code == 401
    assert "set-cookie" not in res.headers
    assert "access_token" not in res.text


@pytest.mark.parametrize("missing", ["code_verifier", "state", "nonce"])
async def test_exchange_requires_pkce_state_and_nonce(anonymous_app: FastAPI, missing: str) -> None:
    """AF-025: code_verifier, state and nonce are mandatory."""
    body = _pkce()
    del body[missing]
    async with _client(anonymous_app) as client:
        res = await client.post("/api/auth/session", json=body)
    assert res.status_code == 422
    assert "set-cookie" not in res.headers


async def test_exchange_rejects_a_short_code_verifier(anonymous_app: FastAPI) -> None:
    async with _client(anonymous_app) as client:
        res = await client.post("/api/auth/session", json=_pkce(code_verifier="too-short"))
    assert res.status_code == 422


async def test_exchange_refuses_a_replayed_state(db_client: tuple[httpx.AsyncClient, FastAPI, str]) -> None:
    client, _, _ = db_client
    body = _pkce()
    assert (await client.post("/api/auth/session", json=body)).status_code == 200
    replay = await client.post("/api/auth/session", json=body)
    assert replay.status_code == 401
    assert "set-cookie" not in replay.headers


async def test_exchange_refuses_an_id_token_with_another_nonce(
    db_client: tuple[httpx.AsyncClient, FastAPI, str],
) -> None:
    client, app, _ = db_client
    app.state.registry.auth.id_token_nonce = secrets.token_urlsafe(STATE_LEN)
    res = await client.post("/api/auth/session", json=_pkce())
    assert res.status_code == 401
    assert "set-cookie" not in res.headers


async def test_exchange_accepts_an_id_token_with_the_same_nonce(
    db_client: tuple[httpx.AsyncClient, FastAPI, str],
) -> None:
    client, app, _ = db_client
    body = _pkce()
    app.state.registry.auth.id_token_nonce = body["nonce"]
    res = await client.post("/api/auth/session", json=body)
    assert res.status_code == 200
    assert REFRESH_COOKIE_NAME in res.cookies


async def test_exchange_outside_development_requires_an_id_token(make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    app = _app(ClaimsAuth(await _create_org(pool)), pool, env="staging")
    async with _client(app) as client:
        res = await client.post("/api/auth/session", json=_pkce())
    assert res.status_code == 401
    assert "set-cookie" not in res.headers


async def test_refresh_cookie_is_encrypted_with_the_configured_key(
    db_client: tuple[httpx.AsyncClient, FastAPI, str],
) -> None:
    """NEW-1: the cookie opens with the boot-resolved key and with no built-in key."""
    from app.core.cookie_crypto import decrypt_cookie  # noqa: PLC0415

    client, app, _ = db_client
    res = await client.post("/api/auth/session", json=_pkce())
    cookie = res.cookies[REFRESH_COOKIE_NAME]
    assert decrypt_cookie(cookie, app.state.session_cookie_key)
    with pytest.raises(Exception, match="invalid"):
        decrypt_cookie(cookie, derive_key("assetflow_dev_cookie_secret_key_32_bytes!"))


async def test_session_without_a_boot_key_is_unavailable() -> None:
    """NEW-1: no key resolved at boot means 503, never a built-in fallback key."""
    app = _app(MockAuthProvider(ProviderContext("development", "auth", Path())), DoublePool())
    del app.state.session_cookie_key
    async with _client(app) as client:
        client.cookies.set(REFRESH_COOKIE_NAME, "anything")
        res = await client.post("/api/auth/refresh")
    assert res.status_code == 503


@pytest.mark.parametrize("path", ["/api/auth/refresh", "/api/auth/logout"])
@pytest.mark.parametrize(
    "headers",
    [
        pytest.param(MARKER, id="missing-origin"),
        pytest.param({"Origin": OTHER_ORIGIN, **MARKER}, id="foreign-origin"),
        pytest.param({"Origin": ORIGIN}, id="missing-marker"),
        pytest.param({"Origin": ORIGIN, "X-Requested-With": "XMLHttpRequest"}, id="wrong-marker"),
        pytest.param({}, id="neither"),
    ],
)
async def test_cookie_endpoints_refuse_a_bad_origin_or_marker(
    db_client: tuple[httpx.AsyncClient, FastAPI, str], path: str, headers: dict[str, str]
) -> None:
    """§B11.2: refresh and logout need an allowed Origin and X-Requested-With: AssetFlow, else 403."""
    client, app, _ = db_client
    cookie = (await client.post("/api/auth/session", json=_pkce())).cookies[REFRESH_COOKIE_NAME]
    async with _client(app, headers) as bare:
        bare.cookies.set(REFRESH_COOKIE_NAME, cookie)
        res = await bare.post(path)
    assert res.status_code == 403
    assert "set-cookie" not in res.headers
    # the refused request neither rotated nor revoked the cookie's token
    client.cookies.set(REFRESH_COOKIE_NAME, cookie)
    assert (await client.post("/api/auth/refresh")).status_code == 200


async def test_logout_with_the_allowed_origin_and_marker_is_ok(
    db_client: tuple[httpx.AsyncClient, FastAPI, str],
) -> None:
    client, _, _ = db_client
    assert (await client.post("/api/auth/logout")).json() == {"ok": True}


SPA_FIELDS = {"code", "redirect_uri", "code_verifier", "state", "nonce"}


async def test_session_request_schema_is_exactly_the_five_spa_fields(
    db_client: tuple[httpx.AsyncClient, FastAPI, str],
) -> None:
    """The body the SPA sends (see frontend features/auth/api.test.ts) is accepted as is."""
    client, _, _ = db_client
    body = _pkce()
    assert set(body) == SPA_FIELDS
    assert (await client.post("/api/auth/session", json=body)).status_code == 200


@pytest.mark.parametrize("extra", ["organization_id", "role", "client_secret", "id_token"])
async def test_session_request_refuses_an_extra_field(anonymous_app: FastAPI, extra: str) -> None:
    async with _client(anonymous_app) as client:
        res = await client.post("/api/auth/session", json={**_pkce(), extra: "x"})
    assert res.status_code == 422
    assert "set-cookie" not in res.headers


async def test_session_exchange_is_rate_limited_per_client(anonymous_app: FastAPI) -> None:
    """PR #291 review: /api/auth/session had no rate limit at all, unlike /api/health."""
    async with _client(anonymous_app) as client:
        for _ in range(AUTH_SESSION_LIMIT):
            res = await client.post("/api/auth/session", json=_pkce())
            assert res.status_code == 401
        limited = await client.post("/api/auth/session", json=_pkce())
    assert limited.status_code == 429
    assert "retry-after" in {h.lower() for h in limited.headers}


async def test_refresh_is_rate_limited_per_client(anonymous_app: FastAPI) -> None:
    """PR #291 review: /api/auth/refresh had no rate limit at all."""
    async with _client(anonymous_app) as client:
        for _ in range(AUTH_REFRESH_LIMIT):
            res = await client.post("/api/auth/refresh")
            assert res.status_code == 401
        limited = await client.post("/api/auth/refresh")
    assert limited.status_code == 429
    assert "retry-after" in {h.lower() for h in limited.headers}
