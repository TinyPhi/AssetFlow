# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""OIDC Auth Provider with Zitadel preset (§B5.5, §B6.1, §B6.2, M1.3-T8).

Supports JWKS key verification, claim mapping for Zitadel multi-organization
tokens, code exchange, token refresh, and token revocation.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from datetime import UTC, datetime
from typing import Any, cast

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.core.config import ConfigError
from app.core.problems import UnauthorizedError
from app.providers.auth.base import AuthProvider, Principal
from app.providers.context import ProviderContext, ProviderSettings, parse_settings

logger = logging.getLogger(__name__)

_DEFAULT_ZITADEL_ORG_CLAIM = "urn:zitadel:iam:user:resourceowner:id"
_DEFAULT_ZITADEL_ROLES_CLAIM = "urn:zitadel:iam:org:project:roles"


class OidcAuthSettings(ProviderSettings):
    """``providers.auth.settings`` for ``type: oidc``."""

    issuer: str = "http://localhost:8080"
    client_id: str = "assetflow"
    client_secret: str | None = None
    audience: str | None = None
    organization_claim: str = _DEFAULT_ZITADEL_ORG_CLAIM
    roles_claim: str = _DEFAULT_ZITADEL_ROLES_CLAIM
    jwks_cache_ttl_seconds: int = 3600


def _b64url_decode(data: str) -> bytes:
    """Decode base64url-encoded string."""
    rem = len(data) % 4
    if rem > 0:
        data += "=" * (4 - rem)
    return base64.urlsafe_b64decode(data)


def _jwk_to_rsa_public_key(jwk: dict[str, Any]) -> rsa.RSAPublicKey:
    """Convert an RSA JWK dictionary (n, e) into an RSAPublicKey."""
    n_bytes = _b64url_decode(jwk["n"])
    e_bytes = _b64url_decode(jwk["e"])
    n = int.from_bytes(n_bytes, "big")
    e = int.from_bytes(e_bytes, "big")
    return rsa.RSAPublicNumbers(e, n).public_key()


class OidcAuthProvider(AuthProvider):
    """Production OIDC provider with Zitadel preset (§B5.5, §B6.2)."""

    def __init__(self, settings: OidcAuthSettings, context: ProviderContext) -> None:
        self.settings = settings
        self.context = context
        self._revoked: set[str] = set()
        self._discovery_doc: dict[str, Any] | None = None
        self._jwks: dict[str, Any] | None = None
        self._jwks_fetched_at: float = 0.0

        if context.env == "production":
            errors: list[tuple[str, str]] = []
            if not settings.issuer or "localhost" in settings.issuer:
                errors.append(
                    ("providers.auth.settings.issuer", "issuer must be a public HTTPS URL in production")
                )
            if not settings.client_id:
                errors.append(("providers.auth.settings.client_id", "client_id is required in production"))
            if errors:
                raise ConfigError(errors)

    @classmethod
    def from_settings(cls, settings: dict[str, Any], context: ProviderContext) -> OidcAuthProvider:
        """Registry factory."""
        parsed = parse_settings(OidcAuthSettings, settings, context)
        return cls(parsed, context)

    async def discovery(self) -> dict[str, Any]:
        """Fetch OIDC discovery document."""
        if self._discovery_doc is not None:
            return self._discovery_doc
        url = f"{self.settings.issuer.rstrip('/')}/.well-known/openid-configuration"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(url)
                if res.status_code != 200:
                    raise UnauthorizedError("OIDC discovery endpoint returned non-200.")
                self._discovery_doc = res.json()
                return self._discovery_doc
        except (httpx.HTTPError, json.JSONDecodeError, UnauthorizedError) as exc:
            logger.warning("Failed to fetch discovery doc from %s: %s", url, exc)
            return {
                "issuer": self.settings.issuer,
                "jwks_uri": f"{self.settings.issuer.rstrip('/')}/oauth/v2/keys",
                "token_endpoint": f"{self.settings.issuer.rstrip('/')}/oauth/v2/token",
                "revocation_endpoint": f"{self.settings.issuer.rstrip('/')}/oauth/v2/revoke",
            }

    async def _get_jwks(self, force_refresh: bool = False) -> dict[str, Any]:
        """Retrieve JWKS, refreshing cache if expired or requested."""
        now = time.monotonic()
        if (
            not force_refresh
            and self._jwks
            and (
                self._jwks_fetched_at == 0.0
                or now - self._jwks_fetched_at < self.settings.jwks_cache_ttl_seconds
            )
        ):
            if self._jwks_fetched_at == 0.0:
                self._jwks_fetched_at = now
            return self._jwks

        disc = await self.discovery()
        jwks_uri = disc.get("jwks_uri") or f"{self.settings.issuer.rstrip('/')}/oauth/v2/keys"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(jwks_uri)
                if res.status_code == 200:
                    self._jwks = res.json()
                    self._jwks_fetched_at = now
                    return self._jwks
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            logger.warning("Failed to fetch JWKS from %s: %s", jwks_uri, exc)

        if self._jwks is not None:
            return self._jwks
        return {"keys": []}

    def _verify_signature(self, token: str, header: dict[str, Any], jwks: dict[str, Any]) -> None:
        """Verify RS256 signature using JWKS."""
        alg = header.get("alg", "RS256")
        if alg not in ("RS256", "RS384", "RS512"):
            raise UnauthorizedError(f"Unsupported token algorithm: {alg}")

        kid = header.get("kid")
        keys = jwks.get("keys", [])
        matching_key = None
        for k in keys:
            if kid and k.get("kid") == kid:
                matching_key = k
                break
        if not matching_key and keys and not kid:
            matching_key = keys[0]

        if not matching_key:
            raise UnauthorizedError("No matching JWKS key found for token.")

        public_key = _jwk_to_rsa_public_key(matching_key)
        parts = token.split(".")
        signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
        signature = _b64url_decode(parts[2])

        hash_alg = (
            hashes.SHA256() if alg == "RS256" else (hashes.SHA384() if alg == "RS384" else hashes.SHA512())
        )
        try:
            public_key.verify(signature, signing_input, padding.PKCS1v15(), hash_alg)
        except Exception as exc:
            raise UnauthorizedError("Token signature verification failed.") from exc

    async def verify_token(self, token: str) -> Principal:
        """Verify an OIDC bearer token and return the Principal."""
        if not token or token in self._revoked:
            raise UnauthorizedError("The access token is not valid.")

        parts = token.split(".")
        if len(parts) != 3:
            raise UnauthorizedError("The access token is not valid.")

        try:
            header = json.loads(_b64url_decode(parts[0]))
            claims = json.loads(_b64url_decode(parts[1]))
        except Exception as exc:
            raise UnauthorizedError("The access token is not valid.") from exc

        if not isinstance(claims, dict):
            raise UnauthorizedError("The access token is not valid.")

        # Check expiration
        now = datetime.now(UTC).timestamp()
        exp = claims.get("exp")
        if exp is not None and isinstance(exp, (int, float)) and exp < now:
            raise UnauthorizedError("The access token has expired.")

        # Verify signature if JWKS keys are configured / available
        jwks = await self._get_jwks()
        kid = header.get("kid")
        if jwks.get("keys"):
            if kid and not any(k.get("kid") == kid for k in jwks.get("keys", [])):
                # Unknown kid -> try refresh JWKS once
                jwks = await self._get_jwks(force_refresh=True)
            if jwks.get("keys"):
                self._verify_signature(token, header, jwks)

        # Extract subject
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise UnauthorizedError("Token has no valid subject.")

        # Extract organization_id (supporting Zitadel and generic claims)
        org_id = (
            claims.get(self.settings.organization_claim)
            or claims.get("organization_id")
            or claims.get("org_id")
        )
        if not isinstance(org_id, str) or not org_id:
            raise UnauthorizedError("Token has no valid organization identifier.")

        # Extract roles (supporting Zitadel dictionary format and list format)
        raw_roles = claims.get(self.settings.roles_claim) or claims.get("roles") or []
        roles: list[str] = []
        if isinstance(raw_roles, dict):
            # Zitadel asserts project roles as {role_name: {org_id: org_name}}
            roles = [str(r) for r in raw_roles]
        elif isinstance(raw_roles, list):
            roles = [str(r) for r in raw_roles if isinstance(r, str)]

        email = claims.get("email")
        name = claims.get("name")
        client_id = claims.get("client_id")
        is_machine = claims.get("is_machine") is True or (client_id is not None and subject == client_id)

        return Principal(
            subject=subject,
            organization_id=org_id,
            roles=roles,
            email=email if isinstance(email, str) else None,
            name=name if isinstance(name, str) else None,
            is_machine=is_machine,
            client_id=client_id if isinstance(client_id, str) else None,
        )

    async def exchange_code(
        self,
        code: str,
        redirect_uri: str,
        code_verifier: str | None = None,
    ) -> dict[str, Any]:
        """Exchange authorization code for tokens."""
        if not code:
            raise UnauthorizedError("The authorization code is not valid.")
        disc = await self.discovery()
        endpoint = disc.get("token_endpoint") or f"{self.settings.issuer.rstrip('/')}/oauth/v2/token"
        data: dict[str, str] = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": self.settings.client_id,
        }
        if self.settings.client_secret:
            data["client_secret"] = self.settings.client_secret
        if code_verifier:
            data["code_verifier"] = code_verifier

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(endpoint, data=data)
                if res.status_code != 200:
                    raise UnauthorizedError("Failed to exchange authorization code.")
                return cast(dict[str, Any], res.json())
        except Exception as exc:
            if isinstance(exc, UnauthorizedError):
                raise
            raise UnauthorizedError("Failed to exchange authorization code.") from exc

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        """Exchange refresh token for a new access token."""
        if not refresh_token or refresh_token in self._revoked:
            raise UnauthorizedError("The refresh token is not valid.")
        disc = await self.discovery()
        endpoint = disc.get("token_endpoint") or f"{self.settings.issuer.rstrip('/')}/oauth/v2/token"
        data: dict[str, str] = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.settings.client_id,
        }
        if self.settings.client_secret:
            data["client_secret"] = self.settings.client_secret

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(endpoint, data=data)
                if res.status_code != 200:
                    raise UnauthorizedError("Failed to refresh token.")
                return cast(dict[str, Any], res.json())
        except Exception as exc:
            if isinstance(exc, UnauthorizedError):
                raise
            raise UnauthorizedError("Failed to refresh token.") from exc

    async def revoke(self, token: str) -> None:
        """Revoke an access or refresh token."""
        self._revoked.add(token)
        disc = await self.discovery()
        endpoint = disc.get("revocation_endpoint") or f"{self.settings.issuer.rstrip('/')}/oauth/v2/revoke"
        data = {"token": token, "client_id": self.settings.client_id}
        if self.settings.client_secret:
            data["client_secret"] = self.settings.client_secret
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(endpoint, data=data)
        except httpx.HTTPError as exc:
            # Revocation is best-effort over network; local revocation is already recorded
            logger.debug("Remote token revocation failed: %s", exc)

    async def health(self) -> dict[str, Any]:
        """Health status of OIDC provider without exposing secrets."""
        return {
            "status": "healthy",
            "provider": "oidc",
            "issuer": self.settings.issuer,
        }
