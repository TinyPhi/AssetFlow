# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Pytest configuration and shared fixtures for AssetFlow test suites."""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.main import Bootstrap, create_app


class _NullRegistry:
    """A provider registry double: the top-level app fixture touches no secrets or providers."""

    async def resolve_secret(self, ref: str) -> str:
        raise AssertionError(f"unexpected secret lookup {ref!r}")


async def _open_null_pool(_config: Any, _resolve_secret: Any) -> object:
    return object()


async def _close_null_pool(_pool: Any) -> None:
    return None


pytest_plugins = ["tests.support.header_identity"]


@pytest.fixture
def app() -> FastAPI:
    """Fixture returning the configured FastAPI application, wired to startup doubles (no database)."""
    return create_app(
        bootstrap=Bootstrap(
            load_config=lambda: {"env": "test"},
            build_registry=lambda _config: _NullRegistry(),
            open_pool=_open_null_pool,
            close_pool=_close_null_pool,
        )
    )


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Fixture providing an asynchronous HTTP test client; the app's lifespan runs around it."""
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac,
    ):
        yield ac
