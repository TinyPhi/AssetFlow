# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The mock sign-in works end to end in development and test (§B13.1, §B11.2).

The mock provider issues the tokens its own ``verify_token`` accepts, so the page the developer sees
(``/api/auth/mock/authorize``), the code exchange (``/api/auth/session``, with its fail-closed
verification, NEW-2) and the next API call all work with no real IdP.
"""

from __future__ import annotations

import html
import re
import secrets
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from pg_harness import PoolFactory
from test_session_flow import Registry, _client, _create_org, _pkce

from app.api.auth import REFRESH_COOKIE_NAME
from app.core.cookie_crypto import derive_key
from app.core.problems import UnauthorizedError
from app.main import create_app
from app.providers.auth.mock import MockAuthProvider
from app.providers.context import ProviderContext

REDIRECT = "http://localhost:5173/auth/callback"


def _mock_provider(idp_org: str, env: str = "development") -> MockAuthProvider:
    return MockAuthProvider.from_settings(
        {"organization_id": idp_org},
        ProviderContext(env, "auth", Path()),  # type: ignore[arg-type]
    )


def _mock_app(provider: MockAuthProvider, pool: object) -> FastAPI:
    app = create_app()
    app.state.config = SimpleNamespace(
        env="development", providers=SimpleNamespace(auth=SimpleNamespace(type="mock"))
    )
    app.state.registry = Registry(provider)
    app.state.pool = pool
    app.state.session_cookie_key = derive_key(secrets.token_hex(16))
    return app


@pytest.fixture
async def mock_client(make_pool: PoolFactory) -> AsyncIterator[httpx.AsyncClient]:
    pool = await make_pool("api")
    idp_org = await _create_org(pool)
    async with _client(_mock_app(_mock_provider(idp_org), pool)) as client:
        yield client


async def test_mock_authorize_to_session_signs_in_a_member(mock_client: httpx.AsyncClient) -> None:
    page = await mock_client.get(
        "/api/auth/mock/authorize", params={"redirect_uri": REDIRECT, "state": "s" * 32}
    )
    assert page.status_code == 200
    links = [html.unescape(h) for h in re.findall(r'href="([^"]+)"', page.text)]
    admin_link = next(link for link in links if "demo-admin" in link)
    code = parse_qs(urlsplit(admin_link).query)["code"][0]

    res = await mock_client.post("/api/auth/session", json=_pkce(code=code, redirect_uri=REDIRECT))
    assert res.status_code == 200
    assert res.json()["access_token"].startswith("mock1.")
    assert REFRESH_COOKIE_NAME in res.cookies
    assert "httponly" in res.headers["set-cookie"].lower()

    me = await mock_client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {res.json()['access_token']}"}
    )
    assert me.status_code == 200
    assert "Ada Lovelace" in me.text


async def test_mock_member_code_also_signs_in(mock_client: httpx.AsyncClient) -> None:
    res = await mock_client.post("/api/auth/session", json=_pkce(code="demo-member"))
    assert res.status_code == 200
    assert REFRESH_COOKIE_NAME in res.cookies


async def test_mock_refuses_an_unknown_code(mock_client: httpx.AsyncClient) -> None:
    res = await mock_client.post("/api/auth/session", json=_pkce(code="whatever"))
    assert res.status_code == 401
    assert "set-cookie" not in res.headers


async def test_mock_tokens_do_not_verify_in_another_process() -> None:
    """The signing key is per process: a token minted elsewhere (or forged) is refused."""
    first, second = _mock_provider(str(uuid4())), _mock_provider(str(uuid4()))
    token = (await first.exchange_code("demo-admin", REDIRECT))["access_token"]
    assert (await first.verify_token(token)).roles == ["admin"]
    with pytest.raises(UnauthorizedError):
        await second.verify_token(token)
    with pytest.raises(UnauthorizedError):
        await first.verify_token(token[:-2] + "xx")


async def test_mock_refresh_keeps_the_identity() -> None:
    provider = _mock_provider("org-x")
    tokens = await provider.exchange_code("demo-member", REDIRECT)
    rotated = await provider.refresh(tokens["refresh_token"])
    assert (await provider.verify_token(rotated["access_token"])).name == "Alan Turing"


def test_mock_stays_refused_outside_development_and_test() -> None:
    from app.core.config import ConfigError  # noqa: PLC0415

    for env in ("staging", "production"):
        with pytest.raises(ConfigError):
            _mock_provider("org-x", env)
