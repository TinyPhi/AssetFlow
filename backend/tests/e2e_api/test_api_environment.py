# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""What the API serves per environment: docs (AF-033), mock sign-in (NEW-3), CORS (AF-023).

The real app factory runs its lifespan with a config object per environment; the registry and the
pool are small doubles, so these tests make no database claims.
"""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.main import Bootstrap, create_app

KEY_REF = "secret://session/cookie#key"
ORIGIN = "https://app.example.org"
OTHER_ORIGIN = "https://evil.example.net"


class _Registry:
    async def resolve_secret(self, ref: str) -> str:
        return secrets.token_urlsafe(48)

    async def health(self) -> dict[str, Any]:
        return {"status": "healthy", "providers": {}}


class _Pool:
    async def fetchval(self, query: str, *args: Any) -> int:
        return 1


def _config(env: str, auth: str = "mock") -> SimpleNamespace:
    return SimpleNamespace(
        env=env,
        session_cookie_key=KEY_REF,
        platform=SimpleNamespace(allowed_origins=[ORIGIN]),
        providers=SimpleNamespace(auth=SimpleNamespace(type=auth)),
    )


@asynccontextmanager
async def _client(config: SimpleNamespace) -> AsyncIterator[httpx.AsyncClient]:
    async def open_pool(cfg: Any, resolve: Any) -> _Pool:
        return _Pool()

    async def close_pool(pool: Any) -> None:
        return None

    app = create_app(
        bootstrap=Bootstrap(
            load_config=lambda: config,
            build_registry=lambda cfg: _Registry(),
            open_pool=open_pool,
            close_pool=close_pool,
        )
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        yield client


DOC_PATHS = ["/docs", "/redoc", "/openapi.json"]


@pytest.mark.parametrize("env", ["production", "staging"])
@pytest.mark.parametrize("path", DOC_PATHS)
async def test_docs_and_openapi_are_off_outside_development_and_test(env: str, path: str) -> None:
    async with _client(_config(env, auth="oidc")) as client:
        assert (await client.get(path)).status_code == 404


@pytest.mark.parametrize("env", ["development", "test"])
@pytest.mark.parametrize("path", DOC_PATHS)
async def test_docs_and_openapi_are_served_in_development_and_test(env: str, path: str) -> None:
    async with _client(_config(env)) as client:
        assert (await client.get(path)).status_code == 200


@pytest.mark.parametrize(
    ("env", "auth", "expected"),
    [
        ("development", "mock", 200),
        ("test", "mock", 200),
        ("development", "oidc", 404),
        ("staging", "mock", 404),
        ("production", "oidc", 404),
    ],
)
async def test_mock_authorize_is_mounted_only_for_mock_auth_in_development_or_test(
    env: str, auth: str, expected: int
) -> None:
    async with _client(_config(env, auth=auth)) as client:
        res = await client.get("/api/auth/mock/authorize", params={"redirect_uri": "/auth/callback"})
        assert res.status_code == expected
        assert (await client.get("/api/health")).status_code == 200


async def test_cors_allows_a_listed_origin_with_credentials() -> None:
    async with _client(_config("production", auth="oidc")) as client:
        res = await client.get("/api/health", headers={"Origin": ORIGIN})
    assert res.headers["access-control-allow-origin"] == ORIGIN
    assert res.headers["access-control-allow-credentials"] == "true"


async def test_cors_gives_an_unlisted_origin_nothing() -> None:
    async with _client(_config("production", auth="oidc")) as client:
        res = await client.get("/api/health", headers={"Origin": OTHER_ORIGIN})
    assert "access-control-allow-origin" not in res.headers


async def test_cors_preflight_for_a_listed_origin_and_refused_for_another() -> None:
    request = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization"}
    async with _client(_config("production", auth="oidc")) as client:
        allowed = await client.options("/api/auth/refresh", headers={"Origin": ORIGIN, **request})
        refused = await client.options("/api/auth/refresh", headers={"Origin": OTHER_ORIGIN, **request})
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == ORIGIN
    assert refused.status_code == 400
    assert "access-control-allow-origin" not in refused.headers
