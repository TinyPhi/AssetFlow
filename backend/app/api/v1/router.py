# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""API v1 router (§B4.1, M1.3-T12)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.api.v1.audit import router as audit_router
from app.api.v1.locations import router as locations_router
from app.api.v1.org_units import router as org_units_router
from app.api.v1.teams import router as teams_router
from app.core.envelope import success_response

router = APIRouter()
router.include_router(audit_router)
router.include_router(org_units_router)
router.include_router(locations_router)
router.include_router(teams_router)


def _request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", "")
    return value if isinstance(value, str) else ""


@router.get("/ping", tags=["system"], summary="Connectivity check")
async def ping(request: Request) -> dict[str, Any]:
    """Lightweight connectivity check."""
    return success_response(data={"pong": True}, request_id=_request_id(request))


@router.get("/info", tags=["system"], summary="Public API information")
async def info(request: Request) -> dict[str, Any]:
    """Public API identity. Environment and build versions are not disclosed anonymously."""
    return success_response(data={"name": "AssetFlow", "api_version": "v1"}, request_id=_request_id(request))
