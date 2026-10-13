# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""CORS from ``platform.allowed_origins`` (AF-023).

The config is loaded in the lifespan, after the middleware stack is built, so this wrapper builds
Starlette's ``CORSMiddleware`` on the first request from ``app.state.config``. Before the config
exists (or with no origins listed) no origin is allowed: no CORS headers are sent. Boot refuses a
``*`` origin outside development and test (:func:`app.api.policy.allowed_origins`).
"""

from __future__ import annotations

from typing import Final

from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from app.api.policy import allowed_origins

ALLOWED_METHODS: Final = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
ALLOWED_HEADERS: Final = [
    "Authorization",
    "Content-Type",
    "If-Match",
    "Idempotency-Key",
    "X-Requested-With",
    "X-Request-ID",
]
EXPOSED_HEADERS: Final = ["X-Request-ID", "Retry-After", "ETag"]
PREFLIGHT_MAX_AGE_SECONDS: Final = 600


class ConfiguredCORSMiddleware:
    """Pure ASGI wrapper: CORS for the origins in the loaded platform config."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._built: tuple[tuple[str, ...], ASGIApp] | None = None

    def _inner(self, scope: Scope) -> ASGIApp:
        config = getattr(scope["app"].state, "config", None)
        origins = tuple(allowed_origins(config)) if config is not None else ()
        if self._built is None or self._built[0] != origins:
            inner = CORSMiddleware(
                self.app,
                allow_origins=list(origins),
                allow_credentials=True,
                allow_methods=ALLOWED_METHODS,
                allow_headers=ALLOWED_HEADERS,
                expose_headers=EXPOSED_HEADERS,
                max_age=PREFLIGHT_MAX_AGE_SECONDS,
            )
            self._built = (origins, inner)
        return self._built[1]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        await self._inner(scope)(scope, receive, send)
