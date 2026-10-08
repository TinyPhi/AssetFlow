# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""``mock`` auth provider for development and tests only (§B6.2). Refused in production.

A mock token is a JSON object of claims, for example
``{"sub": "dev-user", "organization_id": "<uuid>", "roles": ["viewer"]}``. ``sub`` and
``organization_id`` are required; ``roles`` defaults to none; ``email_verified`` defaults to
``true`` (set it to ``false`` explicitly to test the unverified-email path). Anything else (empty,
not JSON, missing or mistyped claims, revoked) raises ``UnauthorizedError``: there is no default
principal.

``exchange_code`` serves the mock sign-in page (§B13.1, minimal profile in development and CI): the
codes ``demo-admin`` and ``demo-member`` yield access tokens signed (HMAC-SHA256) with a random
per-process key, which ``verify_token`` accepts; any other code is refused. The key is never
persisted, so tokens do not survive a restart. The principal belongs to the organization whose
``idp_organization_id`` is ``providers.auth.settings.organization_id`` (default ``mock-org``).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from typing import Any

from app.core.problems import UnauthorizedError
from app.providers.auth.base import AuthProvider, Principal
from app.providers.context import ProviderContext, ProviderSettings, parse_settings, refuse_in_production

_ISSUER = "http://mock-idp.invalid"
_MAX_TOKEN_LENGTH = 8192
_SIGNED_PREFIX = "mock1."
_ACCESS_TOKEN_TTL_SECONDS = 3600
_DEMO_IDENTITIES: dict[str, dict[str, Any]] = {
    "demo-admin": {
        "sub": "mock-ada-lovelace",
        "name": "Ada Lovelace",
        "email": "ada.lovelace@example.org",
        "roles": ["admin"],
    },
    "demo-member": {
        "sub": "mock-alan-turing",
        "name": "Alan Turing",
        "email": "alan.turing@example.org",
        "roles": ["viewer"],
    },
}


class MockAuthSettings(ProviderSettings):
    """``providers.auth.settings`` for ``type: mock``."""

    organization_id: str = "mock-org"


class MockAuthProvider(AuthProvider):
    """Accepts JSON claim tokens and its own signed tokens; issues the latter from ``exchange_code``."""

    def __init__(self, context: ProviderContext, settings: MockAuthSettings | None = None) -> None:
        refuse_in_production(context, "mock auth")
        self._organization_id = (settings or MockAuthSettings()).organization_id
        self._signing_key = secrets.token_bytes(32)
        self._revoked: set[str] = set()
        self._refresh_tokens: dict[str, str] = {}

    @classmethod
    def from_settings(cls, settings: dict[str, Any], context: ProviderContext) -> MockAuthProvider:
        """Registry factory."""
        return cls(context, parse_settings(MockAuthSettings, settings, context))

    async def verify_token(self, token: str) -> Principal:
        """Parse the JSON claims; reject anything malformed."""
        if not token or len(token) > _MAX_TOKEN_LENGTH or token in self._revoked:
            raise UnauthorizedError("The access token is not valid.")
        if token.startswith(_SIGNED_PREFIX):
            return _principal(self._open(token))
        try:
            claims = json.loads(token)
        except ValueError as exc:
            raise UnauthorizedError("The access token is not valid.") from exc
        if not isinstance(claims, dict):
            raise UnauthorizedError("The access token is not valid.")
        return _principal(claims)

    async def discovery(self) -> dict[str, Any]:
        """A minimal discovery document on a reserved, unreachable host."""
        return {
            "issuer": _ISSUER,
            "authorization_endpoint": f"{_ISSUER}/oauth/v2/authorize",
            "token_endpoint": f"{_ISSUER}/oauth/v2/token",
            "jwks_uri": f"{_ISSUER}/oauth/v2/keys",
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
        }

    async def exchange_code(
        self,
        code: str,
        redirect_uri: str,
        code_verifier: str | None = None,
    ) -> dict[str, Any]:
        """Issue signed tokens for a demo code; refuse any other code."""
        identity = _DEMO_IDENTITIES.get(code)
        if identity is None:
            raise UnauthorizedError("The authorization code is not valid.")
        return self._issue(identity["sub"])

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        """Rotate a refresh token issued by this provider."""
        subject = self._refresh_tokens.get(refresh_token)
        if subject is None or refresh_token in self._revoked:
            raise UnauthorizedError("The refresh token is not valid.")
        del self._refresh_tokens[refresh_token]
        self._revoked.add(refresh_token)
        return self._issue(subject or None)

    async def revoke(self, token: str) -> None:
        """Revoke an access or refresh token."""
        self._revoked.add(token)
        self._refresh_tokens.pop(token, None)

    async def health(self) -> dict[str, Any]:
        """Always healthy; flags itself as dev/test only."""
        return {"status": "healthy", "provider": "mock", "note": "development and test only"}

    def _issue(self, subject: str | None = None) -> dict[str, Any]:
        """Fresh tokens; with a demo ``subject`` the access token is signed, else opaque (test seam)."""
        identity = next((i for i in _DEMO_IDENTITIES.values() if i["sub"] == subject), None)
        refresh_token = secrets.token_urlsafe(32)
        self._refresh_tokens[refresh_token] = subject or ""
        access_token = (
            self._sign({**identity, "organization_id": self._organization_id})
            if identity
            else secrets.token_urlsafe(32)
        )
        return {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": _ACCESS_TOKEN_TTL_SECONDS,
            "refresh_token": refresh_token,
        }

    def _mac(self, payload: str) -> str:
        digest = hmac.new(self._signing_key, payload.encode("ascii"), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    def _sign(self, claims: dict[str, Any]) -> str:
        payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode("ascii")
        return f"{_SIGNED_PREFIX}{payload}.{self._mac(payload)}"

    def _open(self, token: str) -> dict[str, Any]:
        """The claims of a token signed by this process; anything else is refused."""
        parts = token[len(_SIGNED_PREFIX) :].split(".")
        if len(parts) != 2 or not hmac.compare_digest(self._mac(parts[0]), parts[1]):
            raise UnauthorizedError("The access token is not valid.")
        try:
            claims = json.loads(base64.urlsafe_b64decode(parts[0] + "=" * (-len(parts[0]) % 4)))
        except ValueError as exc:
            raise UnauthorizedError("The access token is not valid.") from exc
        if not isinstance(claims, dict):
            raise UnauthorizedError("The access token is not valid.")
        return claims


def _principal(claims: dict[str, Any]) -> Principal:
    subject = claims.get("sub")
    organization_id = claims.get("organization_id")
    roles = claims.get("roles", [])
    if not isinstance(subject, str) or not subject:
        raise UnauthorizedError("The access token is not valid.")
    if not isinstance(organization_id, str) or not organization_id:
        raise UnauthorizedError("The access token is not valid.")
    if not isinstance(roles, list) or not all(isinstance(r, str) for r in roles):
        raise UnauthorizedError("The access token is not valid.")
    email = claims.get("email")
    name = claims.get("name")
    client_id = claims.get("client_id")
    return Principal(
        subject=subject,
        organization_id=organization_id,
        roles=list(roles),
        email=email if isinstance(email, str) else None,
        email_verified=claims.get("email_verified", True) is True,
        name=name if isinstance(name, str) else None,
        is_machine=claims.get("is_machine") is True,
        client_id=client_id if isinstance(client_id, str) else None,
    )
