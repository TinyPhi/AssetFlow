# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""AssetFlow application factory and entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan context manager."""
    yield


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    app = FastAPI(
        title="AssetFlow API",
        version="0.1.0",
        description="AssetFlow Open Source Industrial Asset & Maintenance Management",
        lifespan=lifespan,
    )

    @app.get("/healthz", tags=["health"])
    async def health_check() -> dict[str, str]:
        return {"status": "ok", "service": "assetflow"}

    return app


app = create_app()
