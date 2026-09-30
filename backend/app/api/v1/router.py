# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""API v1 router (§B4.1, M1.3-T12)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.core.envelope import success_response

router = APIRouter()


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
