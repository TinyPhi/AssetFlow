# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Public configuration endpoint for SPA bootstrap (§B11.2 step 1).

Delivers client-side auth settings, enabled features, and idle timeout thresholds without exposing
any backend secrets.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(tags=["Config"])


class PublicConfigResponse(BaseModel):
    authority: str
    client_id: str
    redirect_uri: str
    scopes: list[str]
    auth_mode: str
    idle_timeout_minutes: int
    features: list[str]


@router.get("/config/public", response_model=PublicConfigResponse, openapi_extra={"x-assetflow-public": True})
async def get_public_config(request: Request) -> PublicConfigResponse:
    app_state = request.app.state
    config: Any = getattr(app_state, "config", None)
    registry: Any = getattr(app_state, "registry", None)

    auth_type = "mock"
    if registry and hasattr(registry, "auth") and registry.auth:
        auth_type = "oidc" if "oidc" in registry.auth.name.lower() else "mock"

    authority = ""
    client_id = "assetflow-web"
    redirect_uri = "/auth/callback"
    idle_timeout = 30

    if config:
        auth_conf = getattr(config, "auth", None) or {}
        if isinstance(auth_conf, dict):
            client_id = auth_conf.get("client_id", client_id)
            redirect_uri = auth_conf.get("redirect_uri", redirect_uri)
            idle_timeout = auth_conf.get("idle_timeout_minutes", idle_timeout)

    if registry and hasattr(registry, "auth") and registry.auth:
        try:
            disc = await registry.auth.discovery()
            authority = disc.get("issuer", "")
        except Exception:
            authority = ""

    return PublicConfigResponse(
        authority=authority,
        client_id=client_id,
        redirect_uri=redirect_uri,
        scopes=["openid", "profile", "email", "urn:zitadel:iam:org:project:roles"],
        auth_mode=auth_type,
        idle_timeout_minutes=idle_timeout,
        features=["organization", "teams", "members", "notifications", "audit"],
    )
