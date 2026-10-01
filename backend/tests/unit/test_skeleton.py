# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Skeleton tests verifying backend application instantiation and basic routes."""

import pytest
from httpx import AsyncClient

from app.main import app, create_app


def test_app_creation() -> None:
    """Verify that create_app successfully returns a configured FastAPI instance."""
    instance = create_app()
    assert instance.title == "AssetFlow API"
    assert instance.version == "0.1.0"


def test_app_instance() -> None:
    """Verify that the module-level app object is available."""
    assert app is not None
    assert app.title == "AssetFlow API"


@pytest.mark.asyncio
async def test_health_check_endpoint(client: AsyncClient) -> None:
    """Verify that /healthz returns 200 OK and expected JSON payload."""
    response = await client.get("/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "assetflow"
