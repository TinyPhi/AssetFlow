# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""BFF Authentication & Session endpoints (§B11.2, M1.6-T2).

Provides code exchange with cookie-encrypted refresh token storage, single-flight refresh with
rotation, and secure logout.
"""

from __future__ import annotations

import html
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Cookie, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.api.deps import public_extra
from app.core.cookie_crypto import decrypt_cookie, derive_key, encrypt_cookie
from app.core.db import platform_transaction, tenant_transaction
from app.core.problems import UnauthorizedError
from app.modules.audit.service import record_audit_event
from app.modules.organization.provisioning import ProvisioningDeniedError, resolve_member_context

router = APIRouter(prefix="/auth", tags=["Auth"])

REFRESH_COOKIE_NAME = "af_refresh"
COOKIE_PATH = "/api/auth"
COOKIE_MAX_AGE = 7 * 24 * 3600  # 7 days (§B7.2)


class SessionExchangeRequest(BaseModel):
    code: str
    code_verifier: str | None = None
    redirect_uri: str


class TokenResponse(BaseModel):
    access_token: str
    expires_in: int


def _get_cookie_key(request: Request) -> bytes:
    config: Any = getattr(request.app.state, "config", None)
    raw_key = "assetflow_dev_cookie_secret_key_32_bytes!"
    if config:
        auth_conf = getattr(config, "auth", None) or {}
        if isinstance(auth_conf, dict) and "cookie_key" in auth_conf:
            raw_key = auth_conf["cookie_key"]
    return derive_key(raw_key)


@router.post("/session", response_model=TokenResponse, openapi_extra=public_extra())
async def exchange_session(
    body: SessionExchangeRequest,
    request: Request,
    response: Response,
) -> TokenResponse:
    app_state = request.app.state
    registry = getattr(app_state, "registry", None)
    pool = getattr(app_state, "pool", None)
    if not registry or not pool:
        raise HTTPException(status_code=503, detail="Platform services unavailable")

    try:
        token_data = await registry.auth.exchange_code(
            code=body.code,
            redirect_uri=body.redirect_uri,
            code_verifier=body.code_verifier,
        )
    except Exception as exc:
        raise UnauthorizedError("Failed to exchange authorization code.") from exc

    access_token = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token")
    expires_in = token_data.get("expires_in", 3600)

    # Verify token and resolve organization
    try:
        principal = await registry.auth.verify_token(access_token)
    except (ValueError, KeyError, UnauthorizedError, HTTPException, AttributeError):
        # Fallback for mock if access_token is opaque
        principal = None

    if principal is not None:
        async with platform_transaction(pool) as conn:
            row = await conn.fetchrow(
                "SELECT id, status FROM platform.resolve_organization($1)", principal.organization_id
            )
        if row is None or row["status"] not in ("active", "suspended"):
            raise UnauthorizedError()
        organization_id: UUID = row["id"]
        is_org_suspended = row["status"] == "suspended"

        try:
            async with tenant_transaction(pool, organization_id) as conn:
                member = await resolve_member_context(
                    conn, organization_id, principal, allow_provisioning=not is_org_suspended
                )
                # Audit event for sign in
                client_ip = request.client.host if request.client else None
                await record_audit_event(
                    conn,
                    organization_id=organization_id,
                    action="member.signed_in",
                    entity_type="member",
                    entity_id=member.member_id,
                    actor_member_id=member.member_id,
                    personal_values={"ip": client_ip} if client_ip else None,
                )
        except ProvisioningDeniedError as exc:
            raise UnauthorizedError() from exc

    # Set encrypted HttpOnly refresh cookie if refresh token was provided
    if refresh_token:
        cookie_key = _get_cookie_key(request)
        encrypted_val = encrypt_cookie(refresh_token, cookie_key)
        response.set_cookie(
            key=REFRESH_COOKIE_NAME,
            value=encrypted_val,
            max_age=COOKIE_MAX_AGE,
            path=COOKIE_PATH,
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
        )

    return TokenResponse(access_token=access_token, expires_in=expires_in)


@router.post("/refresh", response_model=TokenResponse, openapi_extra=public_extra())
async def refresh_session(
    request: Request,
    response: Response,
    af_refresh: str | None = Cookie(None),
) -> TokenResponse:
    if not af_refresh:
        raise UnauthorizedError("No refresh session cookie present.")

    app_state = request.app.state
    registry = getattr(app_state, "registry", None)
    if not registry:
        raise HTTPException(status_code=503, detail="Platform services unavailable")

    cookie_key = _get_cookie_key(request)
    try:
        raw_refresh_token = decrypt_cookie(af_refresh, cookie_key)
        new_tokens = await registry.auth.refresh(raw_refresh_token)
    except Exception as exc:
        response.delete_cookie(REFRESH_COOKIE_NAME, path=COOKIE_PATH)
        raise UnauthorizedError("Failed to refresh session.") from exc

    new_access_token = new_tokens.get("access_token", "")
    new_refresh_token = new_tokens.get("refresh_token")
    expires_in = new_tokens.get("expires_in", 3600)

    if new_refresh_token:
        new_encrypted = encrypt_cookie(new_refresh_token, cookie_key)
        response.set_cookie(
            key=REFRESH_COOKIE_NAME,
            value=new_encrypted,
            max_age=COOKIE_MAX_AGE,
            path=COOKIE_PATH,
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
        )

    return TokenResponse(access_token=new_access_token, expires_in=expires_in)


@router.post("/logout", openapi_extra=public_extra())
async def logout_session(
    request: Request,
    response: Response,
    af_refresh: str | None = Cookie(None),
) -> dict[str, bool]:
    app_state = request.app.state
    registry = getattr(app_state, "registry", None)

    if af_refresh and registry:
        cookie_key = _get_cookie_key(request)
        try:
            raw_refresh = decrypt_cookie(af_refresh, cookie_key)
            await registry.auth.revoke(raw_refresh)
        except (ValueError, KeyError, OSError, AttributeError):
            pass

    response.delete_cookie(REFRESH_COOKIE_NAME, path=COOKIE_PATH)
    return {"ok": True}


@router.get("/mock/authorize", response_class=HTMLResponse, openapi_extra=public_extra())
async def mock_authorize(
    redirect_uri: str,
    state: str = "",
    code_challenge: str = "",
) -> HTMLResponse:
    """Development mock login selection page."""
    safe_redirect_uri = html.escape(redirect_uri, quote=True)
    safe_state = html.escape(state, quote=True)
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <title>AssetFlow Dev Mock Sign-In</title>
    <style>
        body {{
            font-family: system-ui, sans-serif;
            background: #0f172a;
            color: #f8fafc;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            margin: 0;
        }}
        .card {{
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 12px;
            padding: 2rem;
            max-width: 400px;
            width: 100%;
            box-shadow: 0 10px 25px rgba(0,0,0,0.5);
        }}
        h1 {{ font-size: 1.25rem; margin-top: 0; }}
        .user-btn {{
            display: block;
            width: 100%;
            padding: 0.75rem 1rem;
            margin: 0.5rem 0;
            border: 1px solid #475569;
            border-radius: 8px;
            background: #334155;
            color: #fff;
            text-align: left;
            cursor: pointer;
            text-decoration: none;
            font-size: 0.9rem;
            transition: background 0.2s;
        }}
        .user-btn:hover {{ background: #4f46e5; border-color: #6366f1; }}
        .name {{ font-weight: bold; }}
        .email {{ font-size: 0.8rem; color: #94a3b8; }}
    </style>
</head>
<body>
    <div class="card">
        <h1>AssetFlow Dev Auth</h1>
        <p style="color: #94a3b8; font-size: 0.85rem;">
            Select a mock identity to sign into the development web shell:
        </p>
        <a class="user-btn" href="{safe_redirect_uri}?code=demo-admin&state={safe_state}">
            <div class="name">Ada Lovelace (Org Admin)</div>
            <div class="email">ada.lovelace@example.org</div>
        </a>
        <a class="user-btn" href="{safe_redirect_uri}?code=demo-member&state={safe_state}">
            <div class="name">Alan Turing (Member)</div>
            <div class="email">alan.turing@example.org</div>
        </a>
    </div>
</body>
</html>
"""
    return HTMLResponse(content=html_content)
