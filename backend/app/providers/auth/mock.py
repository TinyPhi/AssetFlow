# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""``mock`` auth provider for development and tests only (§B6.2). Refused in production.

A mock token is a JSON object of claims, for example
``{"sub": "dev-user", "organization_id": "<uuid>", "roles": ["viewer"]}``. ``sub`` and
``organization_id`` are required; ``roles`` defaults to none; ``email_verified`` defaults to
``true`` (set it to ``false`` explicitly to test the unverified-email path). Anything else (empty,
not JSON, missing or mistyped claims, revoked) raises ``UnauthorizedError``: there is no default
principal.
"""

from __future__ import annotations

import json
import secrets
from typing import Any

from app.core.problems import UnauthorizedError
from app.providers.auth.base import AuthProvider, Principal
from app.providers.context import ProviderContext, ProviderSettings, parse_settings, refuse_in_production

_ISSUER = "http://mock-idp.invalid"
_MAX_TOKEN_LENGTH = 8192


class MockAuthSettings(ProviderSettings):
    """``providers.auth.settings`` for ``type: mock`` (none yet)."""


class MockAuthProvider(AuthProvider):
    """Accepts JSON claim tokens; issues random opaque tokens from ``exchange_code``."""

    def __init__(self, context: ProviderContext) -> None:
        refuse_in_production(context, "mock auth")
        self._revoked: set[str] = set()
        self._refresh_tokens: set[str] = set()

    @classmethod
    def from_settings(cls, settings: dict[str, Any], context: ProviderContext) -> MockAuthProvider:
        """Registry factory."""
        parse_settings(MockAuthSettings, settings, context)
        return cls(context)

    async def verify_token(self, token: str) -> Principal:
        """Parse the JSON claims; reject anything malformed."""
        if not token or len(token) > _MAX_TOKEN_LENGTH or token in self._revoked:
            raise UnauthorizedError("The access token is not valid.")
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
        """Issue random opaque tokens (they are not valid access tokens for ``verify_token``)."""
        if not code:
            raise UnauthorizedError("The authorization code is not valid.")
        return self._issue()

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        """Rotate a refresh token issued by this provider."""
        if refresh_token not in self._refresh_tokens or refresh_token in self._revoked:
            raise UnauthorizedError("The refresh token is not valid.")
        self._refresh_tokens.discard(refresh_token)
        self._revoked.add(refresh_token)
        return self._issue()

    async def revoke(self, token: str) -> None:
        """Revoke an access or refresh token."""
        self._revoked.add(token)
        self._refresh_tokens.discard(token)

    async def health(self) -> dict[str, Any]:
        """Always healthy; flags itself as dev/test only."""
        return {"status": "healthy", "provider": "mock", "note": "development and test only"}

    def _issue(self) -> dict[str, Any]:
        refresh_token = secrets.token_urlsafe(32)
        self._refresh_tokens.add(refresh_token)
        return {
            "access_token": secrets.token_urlsafe(32),
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": refresh_token,
        }


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
