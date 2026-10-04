# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""BFF Session flow E2E tests (§B11.2, M1.6-T2)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.main import Bootstrap, create_app
from app.providers.auth.mock import MockAuthProvider
from app.providers.context import ProviderContext


class DoubleRegistry:
    def __init__(self, auth: Any) -> None:
        self.auth = auth

    async def resolve_secret(self, ref: str) -> str:
        return "dummy-secret"


class DoublePool:
    async def execute(self, *args: Any, **kwargs: Any) -> None:
        pass


@pytest.fixture
def test_app() -> FastAPI:
    ctx = ProviderContext(env="development", pillar="auth", base_dir=Path())
    auth = MockAuthProvider(ctx)
    registry = DoubleRegistry(auth)

    config = type(
        "Config",
        (),
        {"auth": {"cookie_key": "test_cookie_key_secret_32bytes!"}},
    )()

    app = create_app(
        bootstrap=Bootstrap(
            load_config=lambda: config,
            build_registry=lambda cfg: registry,
            open_pool=lambda cfg, secret: DoublePool(),
            close_pool=lambda pool: None,
        )
    )
    app.state.config = config
    app.state.registry = registry
    app.state.pool = DoublePool()
    return app


@pytest.mark.asyncio
async def test_public_config_endpoint(test_app: FastAPI):
    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/config/public")
        assert res.status_code == 200
        data = res.json()
        assert "auth_mode" in data
        assert "client_id" in data
        assert "redirect_uri" in data
        assert "idle_timeout_minutes" in data


@pytest.mark.asyncio
async def test_session_exchange_and_refresh_rotation(test_app: FastAPI):
    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Exchange code
        res = await client.post(
            "/api/auth/session",
            json={"code": "valid-auth-code", "redirect_uri": "/auth/callback"},
        )
        assert res.status_code == 200
        body = res.json()
        assert "access_token" in body
        assert "expires_in" in body
        assert "af_refresh" in res.cookies
        first_refresh_cookie = res.cookies["af_refresh"]

        # 2. Refresh with cookie
        client.cookies.set("af_refresh", first_refresh_cookie)
        res2 = await client.post("/api/auth/refresh")
        assert res2.status_code == 200
        body2 = res2.json()
        assert "access_token" in body2
        assert "af_refresh" in res2.cookies
        second_refresh_cookie = res2.cookies["af_refresh"]
        assert first_refresh_cookie != second_refresh_cookie

        # 3. Old cookie should now fail (rotation / replay prevention)
        client.cookies.set("af_refresh", first_refresh_cookie)
        res3 = await client.post("/api/auth/refresh")
        assert res3.status_code == 401

        # 4. Logout revokes and clears cookie
        client.cookies.set("af_refresh", second_refresh_cookie)
        res_logout = await client.post("/api/auth/logout")
        assert res_logout.status_code == 200


@pytest.mark.asyncio
async def test_mock_authorize_page(test_app: FastAPI):
    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/auth/mock/authorize?redirect_uri=/callback")
        assert res.status_code == 200
        assert "AssetFlow Dev Auth" in res.text
