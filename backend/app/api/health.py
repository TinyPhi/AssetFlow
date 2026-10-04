# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Health endpoints (§B6.1 rule 4, M1.3-T12).

* ``GET /healthz``: liveness, no dependencies checked.
* ``GET /api/health``: public readiness. Returns only ``{"status": "ok"}`` (200) or
  ``{"status": "unavailable"}`` (503). No environment, versions, provider names or error text.
* ``GET /api/health/providers``: platform admins only. Each pillar and the database report a
  sanitized state (``healthy``, ``degraded``, ``unhealthy`` or ``unknown``) and nothing else.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any, Final, Literal, Protocol

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.deps import require_platform_admin

State = Literal["healthy", "degraded", "unhealthy", "unknown"]

PILLARS: Final = ("auth", "secrets", "telemetry", "events")
CHECK_TIMEOUT_SECONDS: Final = 2.0
_STATES: Final[frozenset[str]] = frozenset({"healthy", "degraded", "unhealthy"})
_NO_STORE: Final = {"Cache-Control": "no-store"}

_log = logging.getLogger("assetflow.health")

router = APIRouter(tags=["health"])


class HealthReporter(Protocol):
    """What the health endpoints need from the provider registry."""

    async def health(self) -> Mapping[str, Any]: ...


class ReadinessPool(Protocol):
    """What the health endpoints need from the database pool."""

    async def fetchval(self, query: str, *args: Any) -> Any: ...


def _state(value: Any) -> State:
    if isinstance(value, Mapping):
        value = value.get("status")
    if isinstance(value, str) and value in _STATES:
        return value  # type: ignore[return-value]  # narrowed by the membership test
    return "unknown"


async def _database_state(pool: ReadinessPool | None) -> State:
    if pool is None:
        return "unhealthy"
    try:
        async with asyncio.timeout(CHECK_TIMEOUT_SECONDS):
            await pool.fetchval("SELECT 1")
    except Exception as exc:  # noqa: BLE001 - any driver error means "not ready"; logged, never returned
        _log.warning("health.database_unavailable", extra={"error_type": type(exc).__name__})
        return "unhealthy"
    return "healthy"


async def _provider_states(registry: HealthReporter | None) -> tuple[State, dict[str, State]]:
    if registry is None:
        return "unhealthy", dict.fromkeys(PILLARS, "unknown")
    try:
        async with asyncio.timeout(CHECK_TIMEOUT_SECONDS):
            report = await registry.health()
    except Exception as exc:  # noqa: BLE001 - a failing health() means "not ready"; logged, never returned
        _log.warning("health.providers_unavailable", extra={"error_type": type(exc).__name__})
        return "unhealthy", dict.fromkeys(PILLARS, "unknown")
    providers = report.get("providers")
    per_pillar: Mapping[str, Any] = providers if isinstance(providers, Mapping) else {}
    return _state(report), {name: _state(per_pillar.get(name)) for name in PILLARS}


async def _collect(request: Request) -> tuple[bool, State, dict[str, State], State]:
    state = request.app.state
    registry: HealthReporter | None = getattr(state, "registry", None)
    pool: ReadinessPool | None = getattr(state, "pool", None)
    (overall, pillars), database = await asyncio.gather(_provider_states(registry), _database_state(pool))
    ready = overall in ("healthy", "degraded") and database == "healthy"
    return ready, overall, pillars, database


@router.get("/healthz", summary="Liveness probe", openapi_extra={"x-assetflow-public": True})
async def liveness() -> dict[str, str]:
    """The process is up and serving HTTP; no dependency is checked."""
    return {"status": "ok", "service": "assetflow"}


@router.get(
    "/api/health",
    summary="Readiness probe",
    responses={503: {"description": "Not ready"}},
    openapi_extra={"x-assetflow-public": True},
)
async def readiness(request: Request) -> JSONResponse:
    """Public readiness: ``ok`` with 200 when the database and providers are ready, else 503."""
    ready, *_ = await _collect(request)
    if ready:
        return JSONResponse({"status": "ok"}, headers=_NO_STORE)
    return JSONResponse({"status": "unavailable"}, status_code=503, headers=_NO_STORE)


@router.get(
    "/api/health/providers",
    summary="Provider and database health (platform admin)",
    dependencies=[Depends(require_platform_admin)],
    responses={401: {"description": "Not signed in as a platform admin"}},
    openapi_extra={"x-assetflow-permission": "platform.admin"},
)
async def provider_health(request: Request) -> JSONResponse:
    """Sanitized state per provider pillar and for the database; 503 when not ready."""
    ready, overall, pillars, database = await _collect(request)
    body = {
        "status": "ok" if ready else "unavailable",
        "providers": {name: {"status": st} for name, st in pillars.items()},
        "providers_overall": overall,
        "database": {"status": database},
    }
    return JSONResponse(body, status_code=200 if ready else 503, headers=_NO_STORE)
