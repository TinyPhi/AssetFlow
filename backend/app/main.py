# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""AssetFlow API application factory (§B4.1, M1.3-T12).

``create_app()`` only wires middleware, exception handlers and routers; it does no I/O. The work
happens in the lifespan: load config, build the provider registry, open the ``api`` database pool
(its password resolved through the registry's secrets provider), publish them on ``app.state``
(``config``, ``registry``, ``pool``) and close the pool on shutdown.

Run with ``uvicorn --factory app.main:create_app``. ``app.main:app`` also works: the module-level
``app`` is built lazily on first access, never at import.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Final
from uuid import UUID

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.health import router as health_router
from app.api.v1.router import router as v1_router
from app.core.auth_middleware import AuthMiddleware
from app.core.ids import uuid7_str
from app.core.problems import (
    ProblemError,
    http_exception_handler,
    problem_error_handler,
    request_validation_handler,
    unhandled_exception_handler,
)

logger = logging.getLogger("assetflow.main")

API_TITLE: Final = "AssetFlow API"
API_VERSION: Final = "0.1.0"
REQUEST_ID_HEADER: Final = "x-request-id"
REQUEST_ID_MAX_LEN: Final = 64

SecretResolver = Callable[[str], Awaitable[str]]


def _default_load_config() -> Any:
    from app.core.config import load_config  # noqa: PLC0415 - imported at lifespan time, not import time

    return load_config()


def _default_build_registry(config: Any) -> Any:
    from app.providers.registry import ProviderRegistry  # noqa: PLC0415 - see _default_load_config

    return ProviderRegistry.from_config(config)


async def _default_open_pool(config: Any, resolve_secret: SecretResolver) -> Any:
    from app.core.db import init_pool  # noqa: PLC0415 - see _default_load_config

    return await init_pool(config.database, "api", resolve_secret)


async def _default_close_pool(pool: Any) -> None:
    from app.core.db import close_pool  # noqa: PLC0415 - see _default_load_config

    await close_pool(pool)


@dataclass(frozen=True)
class Bootstrap:
    """The startup steps the lifespan runs; tests replace individual steps with test doubles."""

    load_config: Callable[[], Any] = field(default=_default_load_config)
    build_registry: Callable[[Any], Any] = field(default=_default_build_registry)
    open_pool: Callable[[Any, SecretResolver], Awaitable[Any]] = field(default=_default_open_pool)
    close_pool: Callable[[Any], Awaitable[None]] = field(default=_default_close_pool)


def _valid_request_id(raw: str) -> str | None:
    """Accept a client X-Request-ID only if it is a UUID of at most 64 characters (normalized)."""
    if not raw or len(raw) > REQUEST_ID_MAX_LEN:
        return None
    try:
        return str(UUID(raw))
    except ValueError:
        return None


class RequestIdMiddleware:
    """Set ``request.state.request_id`` and the ``X-Request-ID`` response header.

    A client-sent value is kept only if it is a valid UUID (<= 64 chars); anything else is replaced
    by a fresh UUIDv7, so logs never carry attacker-controlled text as a request id.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        raw = ""
        for name, value in scope.get("headers", []):
            if name.decode("latin-1").lower() == REQUEST_ID_HEADER:
                raw = value.decode("latin-1")
                break
        request_id = _valid_request_id(raw) or uuid7_str()
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"]
                headers.append((b"x-request-id", request_id.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_id)


def _make_lifespan(bootstrap: Bootstrap) -> Callable[[FastAPI], Any]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        config = bootstrap.load_config()
        registry = bootstrap.build_registry(config)
        if inspect.isawaitable(registry):
            registry = await registry
        pool = await bootstrap.open_pool(config, registry.resolve_secret)
        app.state.config = config
        app.state.registry = registry
        app.state.pool = pool
        logger.info("app.started")
        try:
            yield
        finally:
            app.state.pool = None
            try:
                await bootstrap.close_pool(pool)
            finally:
                closer = getattr(registry, "aclose", None)
                if closer is not None:
                    await closer()
            logger.info("app.stopped")

    return lifespan


def create_app(*, bootstrap: Bootstrap | None = None) -> FastAPI:
    """Build the FastAPI application. No config is read and nothing is connected until startup."""
    app = FastAPI(
        title=API_TITLE,
        version=API_VERSION,
        description="AssetFlow asset and maintenance management API",
        lifespan=_make_lifespan(bootstrap or Bootstrap()),
    )
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(AuthMiddleware)

    app.add_exception_handler(ProblemError, problem_error_handler)
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    app.include_router(health_router)
    app.include_router(v1_router, prefix="/api/v1")
    return app


_lazy_app: FastAPI | None = None


def __getattr__(name: str) -> Any:
    """Build the module-level ``app`` on first access (for ``uvicorn app.main:app``)."""
    global _lazy_app  # noqa: PLW0603 - memoized lazy factory
    if name == "app":
        if _lazy_app is None:
            _lazy_app = create_app()
        return _lazy_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
