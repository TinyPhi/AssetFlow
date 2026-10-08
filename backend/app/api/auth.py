# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""BFF Authentication & Session endpoints (§B11.2, M1.6-T2).

Provides code exchange with cookie-encrypted refresh token storage, single-flight refresh with
rotation, and secure logout.

``POST /api/auth/session`` takes ``{code, code_verifier, state, nonce, redirect_uri}`` (AF-025):

* ``code_verifier`` is required (RFC 7636: 43 to 128 unreserved characters);
* ``state`` is required and single-use: a replayed value is refused;
* ``nonce`` is required and must equal the ``nonce`` claim of the ``id_token`` the IdP returns
  (an exchange without an ``id_token`` is accepted only in development and test);
* the access token must verify into a principal, or the exchange fails closed: 401, no cookie.

``POST /api/auth/refresh`` and ``/api/auth/logout`` ride on the refresh cookie, so they also require
an ``Origin`` listed in ``platform.allowed_origins`` and the header ``X-Requested-With: AssetFlow``;
otherwise 403 (§B11.2, CSRF defence in depth beside ``SameSite=Strict``).
"""

from __future__ import annotations

import base64
import binascii
import html
import json
import secrets
import time
from collections import OrderedDict
from typing import Any, Final
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import public_extra
from app.api.policy import allowed_origins, is_relaxed, mock_auth_enabled
from app.core.cookie_crypto import decrypt_cookie, encrypt_cookie
from app.core.db import platform_transaction, tenant_transaction
from app.core.problems import (
    NotFoundError,
    PermissionDeniedError,
    ProblemError,
    ServiceUnavailableError,
    UnauthorizedError,
)
from app.modules.audit.service import record_audit_event
from app.modules.organization.provisioning import ProvisioningDeniedError, resolve_member_context

router = APIRouter(prefix="/auth", tags=["Auth"])

REFRESH_COOKIE_NAME = "af_refresh"
COOKIE_PATH = "/api/auth"
COOKIE_MAX_AGE = 7 * 24 * 3600  # 7 days (§B7.2)


STATE_TTL_SECONDS: Final = 600
STATE_CACHE_MAX: Final = 10_000
_TOKEN_CHARS: Final = r"^[A-Za-z0-9\-._~]+$"  # noqa: S105 - a character class, not a secret


class SessionExchangeRequest(BaseModel):
    """The PKCE session exchange; every field is required, unknown fields are refused (AF-025)."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=2048)
    code_verifier: str = Field(min_length=43, max_length=128, pattern=_TOKEN_CHARS)
    state: str = Field(min_length=16, max_length=256, pattern=_TOKEN_CHARS)
    nonce: str = Field(min_length=16, max_length=256, pattern=_TOKEN_CHARS)
    redirect_uri: str = Field(min_length=1, max_length=2048)


CSRF_HEADER: Final = "x-requested-with"
CSRF_HEADER_VALUE: Final = "AssetFlow"


def require_cookie_request_guard(request: Request) -> None:
    """403 unless the request names an allowed ``Origin`` and carries ``X-Requested-With: AssetFlow``."""
    config = getattr(request.app.state, "config", None)
    origins = allowed_origins(config) if config is not None else []
    origin = request.headers.get("origin")
    origin_allowed = origin is not None and (origin in origins or ("*" in origins and is_relaxed(config)))
    marker = request.headers.get(CSRF_HEADER)
    if not origin_allowed or marker != CSRF_HEADER_VALUE:
        raise PermissionDeniedError("The request origin is not allowed.")


class TokenResponse(BaseModel):
    access_token: str
    expires_in: int


def _get_cookie_key(request: Request) -> bytes:
    """The refresh-cookie key resolved at boot from ``session_cookie_key``; never a built-in value."""
    key: bytes | None = getattr(request.app.state, "session_cookie_key", None)
    if not key:
        raise ServiceUnavailableError("The session service is not configured.")
    return key


def _consume_state(request: Request, state: str) -> None:
    """Accept each ``state`` once (replay protection); raise ``UnauthorizedError`` on reuse."""
    seen: OrderedDict[str, float] | None = getattr(request.app.state, "oauth_states_seen", None)
    if seen is None:
        seen = OrderedDict()
        request.app.state.oauth_states_seen = seen
    now = time.monotonic()
    while seen and (len(seen) >= STATE_CACHE_MAX or next(iter(seen.values())) <= now - STATE_TTL_SECONDS):
        seen.popitem(last=False)
    if state in seen:
        raise UnauthorizedError("The sign-in request was already used.")
    seen[state] = now


def _id_token_nonce(id_token: str) -> str | None:
    """The ``nonce`` claim of an ID token received directly from the token endpoint over TLS.

    OIDC Core 3.1.3.7 lets a client skip the signature check for such a token; only the claim is
    read here, never an identity.
    """
    parts = id_token.split(".")
    if len(parts) != 3:
        return None
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, binascii.Error):
        return None
    nonce = claims.get("nonce") if isinstance(claims, dict) else None
    return nonce if isinstance(nonce, str) else None


def _check_nonce(request: Request, token_data: dict[str, Any], nonce: str) -> None:
    id_token = token_data.get("id_token")
    if not id_token:
        if is_relaxed(getattr(request.app.state, "config", None)):
            return
        raise UnauthorizedError("The sign-in response carries no identity token.")
    received = _id_token_nonce(id_token) if isinstance(id_token, str) else None
    if received is None or not secrets.compare_digest(received, nonce):
        raise UnauthorizedError("The sign-in response does not match the request.")


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

    _consume_state(request, body.state)
    try:
        token_data = await registry.auth.exchange_code(
            code=body.code,
            redirect_uri=body.redirect_uri,
            code_verifier=body.code_verifier,
        )
    except ProblemError:
        raise
    except Exception as exc:
        raise UnauthorizedError("Failed to exchange authorization code.") from exc

    _check_nonce(request, token_data, body.nonce)

    access_token = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token")
    expires_in = token_data.get("expires_in", 3600)

    # Fail closed (NEW-2): without a verified principal there is no session, cookie or token.
    try:
        principal = await registry.auth.verify_token(access_token)
    except ProblemError:
        raise
    except Exception as exc:
        raise UnauthorizedError("The access token is not valid.") from exc

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
            client_ip = request.client.host if request.client else None
            await record_audit_event(
                conn,
                organization_id=organization_id,
                action="member.signed_in",
                entity_type="member",
                entity_id=UUID(member.member_id),
                actor_member_id=UUID(member.member_id),
                personal_values={"ip": client_ip} if client_ip else None,
            )
    except ProvisioningDeniedError as exc:
        raise UnauthorizedError() from exc

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


@router.post(
    "/refresh",
    dependencies=[Depends(require_cookie_request_guard)],
    response_model=TokenResponse,
    openapi_extra=public_extra(),
)
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


@router.post("/logout", dependencies=[Depends(require_cookie_request_guard)], openapi_extra=public_extra())
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


def require_mock_auth(request: Request) -> None:
    """Defense in depth for NEW-3: 404 unless mock auth is enabled for this environment."""
    if not mock_auth_enabled(getattr(request.app.state, "config", None)):
        raise NotFoundError()


mock_router = APIRouter(prefix="/auth/mock", tags=["Auth"], dependencies=[Depends(require_mock_auth)])


@mock_router.get("/authorize", response_class=HTMLResponse, openapi_extra=public_extra())
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
