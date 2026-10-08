# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""OIDC Auth Provider with Zitadel preset (§B5.5, §B6.1, §B6.2, M1.3-T8).

Supports JWKS key verification, claim mapping for Zitadel multi-organization
tokens, code exchange, token refresh, and token revocation.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, cast

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.core.config import ConfigError
from app.core.problems import SecretsUnavailableError, UnauthorizedError
from app.providers.auth.base import AuthProvider, Principal
from app.providers.context import ProviderContext, ProviderSettings, parse_settings

logger = logging.getLogger(__name__)

_DEFAULT_ZITADEL_ORG_CLAIM = "urn:zitadel:iam:user:resourceowner:id"
_DEFAULT_ZITADEL_ROLES_CLAIM = "urn:zitadel:iam:org:project:roles"
_CLOCK_LEEWAY_SECONDS = 60
_DISCOVERY_FAILURE_TTL_SECONDS = 30.0
_ALLOWED_ALGS: dict[str, type[hashes.HashAlgorithm]] = {
    "RS256": hashes.SHA256,
    "RS384": hashes.SHA384,
    "RS512": hashes.SHA512,
}
_INVALID = "The access token is not valid."


class OidcAuthSettings(ProviderSettings):
    """``providers.auth.settings`` for ``type: oidc``."""

    issuer: str = "http://localhost:19081"
    client_id: str = "assetflow"
    client_secret: str | None = None
    audience: str | None = None
    organization_claim: str = _DEFAULT_ZITADEL_ORG_CLAIM
    roles_claim: str = _DEFAULT_ZITADEL_ROLES_CLAIM
    jwks_cache_ttl_seconds: int = 3600
    revocation_cache_size: int = 10_000


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
    """Production OIDC provider with Zitadel preset (§B5.5, §B6.2).

    Revocation is a local, bounded (LRU) denylist, so it only covers this process. Run the identity
    provider with short access-token lifetimes (5 minutes recommended); a shared denylist is a
    backlog item (AF-012).
    """

    def __init__(
        self,
        settings: OidcAuthSettings,
        context: ProviderContext,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.context = context
        self._transport = transport
        self.secret_resolver: Callable[[str], Awaitable[str]] | None = None  # set by the app (AF-015)
        self._revoked: OrderedDict[str, None] = OrderedDict()
        self._discovery_doc: dict[str, Any] | None = None
        self._discovery_failed_at: float | None = None
        self._discovery_lock = asyncio.Lock()
        self._jwks_lock = asyncio.Lock()
        self._jwks: dict[str, Any] | None = None
        self._jwks_fetched_at: float = 0.0

        errors: list[tuple[str, str]] = []
        if context.env not in ("development", "test"):
            if not settings.issuer.lower().startswith("https://"):
                errors.append(("providers.auth.settings.issuer", "issuer must be an https:// URL"))
            if not settings.audience:
                errors.append(
                    ("providers.auth.settings.audience", "audience is required outside development")
                )
        if context.env == "production":
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

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, transport=self._transport)

    def _lenient(self) -> bool:
        """Development-only conveniences: discovery fallback and generic claim fallbacks."""
        return self.context.env == "development"

    def _is_revoked(self, token: str) -> bool:
        if token in self._revoked:
            self._revoked.move_to_end(token)
            return True
        return False

    def _remember_revoked(self, token: str) -> None:
        self._revoked[token] = None
        self._revoked.move_to_end(token)
        while len(self._revoked) > max(1, self.settings.revocation_cache_size):
            self._revoked.popitem(last=False)

    def _fallback_discovery(self) -> dict[str, Any]:
        base = self.settings.issuer.rstrip("/")
        return {
            "issuer": self.settings.issuer,
            "jwks_uri": f"{base}/oauth/v2/keys",
            "token_endpoint": f"{base}/oauth/v2/token",
            "revocation_endpoint": f"{base}/oauth/v2/revoke",
        }

    def _discovery_failure(self) -> dict[str, Any]:
        if self._lenient():
            return self._fallback_discovery()
        raise UnauthorizedError("OIDC discovery is unavailable.")

    async def discovery(self) -> dict[str, Any]:
        """Fetch the OIDC discovery document once (single-flight); failures are cached briefly."""
        if self._discovery_doc is not None:
            return self._discovery_doc
        async with self._discovery_lock:
            if self._discovery_doc is not None:
                return self._discovery_doc
            failed_at = self._discovery_failed_at
            if failed_at is not None and time.monotonic() - failed_at < _DISCOVERY_FAILURE_TTL_SECONDS:
                return self._discovery_failure()
            url = f"{self.settings.issuer.rstrip('/')}/.well-known/openid-configuration"
            try:
                async with self._client(10.0) as client:
                    res = await client.get(url)
                if res.status_code != 200:
                    raise UnauthorizedError("OIDC discovery endpoint returned non-200.")
                doc = res.json()
                if not isinstance(doc, dict):
                    raise UnauthorizedError("OIDC discovery document is not an object.")
            except (httpx.HTTPError, ValueError, UnauthorizedError) as exc:
                logger.warning("Failed to fetch discovery doc from %s: %s", url, exc)
                self._discovery_failed_at = time.monotonic()
                return self._discovery_failure()
            if doc.get("issuer") != self.settings.issuer:
                # A mismatched issuer is never trusted, not even in development.
                self._discovery_failed_at = time.monotonic()
                raise UnauthorizedError("OIDC discovery issuer does not match the configured issuer.")
            self._discovery_failed_at = None
            self._discovery_doc = doc
            return doc

    async def _get_jwks(self, force_refresh: bool = False) -> dict[str, Any]:
        """Retrieve JWKS (single-flight), refreshing the cache if expired or requested."""
        requested_at = time.monotonic()
        async with self._jwks_lock:
            now = time.monotonic()
            if self._jwks:
                if self._jwks_fetched_at == 0.0:
                    self._jwks_fetched_at = now
                refreshed_meanwhile = force_refresh and self._jwks_fetched_at >= requested_at
                fresh = now - self._jwks_fetched_at < self.settings.jwks_cache_ttl_seconds
                if (fresh and not force_refresh) or refreshed_meanwhile:
                    return self._jwks

            disc = await self.discovery()
            jwks_uri = disc.get("jwks_uri") or f"{self.settings.issuer.rstrip('/')}/oauth/v2/keys"
            try:
                async with self._client(10.0) as client:
                    res = await client.get(jwks_uri)
                if res.status_code == 200:
                    doc = res.json()
                    if isinstance(doc, dict):
                        self._jwks = doc
                        self._jwks_fetched_at = time.monotonic()
                        return doc
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("Failed to fetch JWKS from %s: %s", jwks_uri, exc)

            if self._jwks is not None:
                return self._jwks
            return {"keys": []}

    def _verify_signature(self, token: str, header: dict[str, Any], jwks: dict[str, Any]) -> None:
        """Verify an RS256/384/512 signature using JWKS."""
        alg = header.get("alg")
        if alg not in _ALLOWED_ALGS:
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

        try:
            public_key.verify(signature, signing_input, padding.PKCS1v15(), _ALLOWED_ALGS[alg]())
        except Exception as exc:
            raise UnauthorizedError("Token signature verification failed.") from exc

    def _check_claims(self, claims: dict[str, Any]) -> None:
        """Validate exp, nbf, iat, iss and aud (60 s clock leeway on nbf/iat)."""
        now = datetime.now(UTC).timestamp()
        # A token with no exp claim at all is rejected, not treated as eternal.
        exp = claims.get("exp")
        if isinstance(exp, bool) or not isinstance(exp, (int, float)):
            raise UnauthorizedError(_INVALID)
        if exp < now:
            raise UnauthorizedError("The access token has expired.")
        for name in ("nbf", "iat"):
            value = claims.get(name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise UnauthorizedError(_INVALID)
            if value > now + _CLOCK_LEEWAY_SECONDS:
                raise UnauthorizedError("The access token is not yet valid.")

        if claims.get("iss") != self.settings.issuer:
            raise UnauthorizedError(_INVALID)

        expected_aud = self.settings.audience
        if expected_aud is None and self.context.env not in ("development", "test"):
            expected_aud = self.settings.client_id
        if expected_aud is not None:
            aud = claims.get("aud")
            audiences = [aud] if isinstance(aud, str) else (aud if isinstance(aud, list) else [])
            if expected_aud not in audiences:
                raise UnauthorizedError(_INVALID)

    def _extract_roles(self, claims: dict[str, Any], org_id: str) -> list[str]:
        """Roles granted in the token's own organization only (AF-011)."""
        raw = claims.get(self.settings.roles_claim)
        if raw is None and self._lenient():
            raw = claims.get("roles")
        if isinstance(raw, dict):
            # Zitadel asserts project roles as {role_name: {org_id: org_name}}
            return [str(role) for role, orgs in raw.items() if isinstance(orgs, dict) and org_id in orgs]
        if isinstance(raw, list) and self._lenient():
            return [str(r) for r in raw if isinstance(r, str)]
        return []

    async def verify_token(self, token: str) -> Principal:
        """Verify an OIDC bearer token and return the Principal."""
        if not token or self._is_revoked(token):
            raise UnauthorizedError(_INVALID)

        parts = token.split(".")
        if len(parts) != 3:
            raise UnauthorizedError(_INVALID)

        try:
            header = json.loads(_b64url_decode(parts[0]))
            claims = json.loads(_b64url_decode(parts[1]))
        except Exception as exc:
            raise UnauthorizedError(_INVALID) from exc

        if not isinstance(header, dict) or not isinstance(claims, dict):
            raise UnauthorizedError(_INVALID)
        if header.get("alg") not in _ALLOWED_ALGS:
            raise UnauthorizedError(_INVALID)

        # Verify signature. An empty JWKS (fetch failure, outage) fails closed: verification is
        # never silently skipped, or any unsigned claim set would be accepted as authentic.
        jwks = await self._get_jwks()
        kid = header.get("kid")
        if kid and not any(k.get("kid") == kid for k in jwks.get("keys", [])):
            # Unknown kid -> try refresh JWKS once
            jwks = await self._get_jwks(force_refresh=True)
        if not jwks.get("keys"):
            raise UnauthorizedError("Unable to verify the access token signature.")
        self._verify_signature(token, header, jwks)

        self._check_claims(claims)

        # Extract subject
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise UnauthorizedError("Token has no valid subject.")

        # Organization: the configured (Zitadel resource-owner) claim; generic fallbacks in development.
        org_id = claims.get(self.settings.organization_claim)
        if not org_id and self._lenient():
            org_id = claims.get("organization_id") or claims.get("org_id")
        if not isinstance(org_id, str) or not org_id:
            raise UnauthorizedError("Token has no valid organization identifier.")

        roles = self._extract_roles(claims, org_id)

        email = claims.get("email")
        name = claims.get("name")
        client_id = claims.get("client_id")
        is_machine = claims.get("is_machine") is True or (client_id is not None and subject == client_id)

        return Principal(
            subject=subject,
            organization_id=org_id,
            roles=roles,
            email=email if isinstance(email, str) else None,
            email_verified=claims.get("email_verified") is True,
            name=name if isinstance(name, str) else None,
            is_machine=is_machine,
            client_id=client_id if isinstance(client_id, str) else None,
        )

    async def _client_secret(self) -> str | None:
        """The OIDC client secret; a ``secret://`` reference is resolved through the secrets provider."""
        raw = self.settings.client_secret
        if not raw or not raw.startswith("secret://"):
            return raw
        if self.secret_resolver is None:
            raise SecretsUnavailableError(
                "OIDC client secret is a reference but no secrets provider is wired."
            )
        return await self.secret_resolver(raw)

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
        client_secret = await self._client_secret()
        if client_secret:
            data["client_secret"] = client_secret
        if code_verifier:
            data["code_verifier"] = code_verifier

        try:
            async with self._client(10.0) as client:
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
        if not refresh_token or self._is_revoked(refresh_token):
            raise UnauthorizedError("The refresh token is not valid.")
        disc = await self.discovery()
        endpoint = disc.get("token_endpoint") or f"{self.settings.issuer.rstrip('/')}/oauth/v2/token"
        data: dict[str, str] = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.settings.client_id,
        }
        client_secret = await self._client_secret()
        if client_secret:
            data["client_secret"] = client_secret

        try:
            async with self._client(10.0) as client:
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
        self._remember_revoked(token)
        try:
            disc = await self.discovery()
            endpoint = (
                disc.get("revocation_endpoint") or f"{self.settings.issuer.rstrip('/')}/oauth/v2/revoke"
            )
            data = {"token": token, "client_id": self.settings.client_id}
            if self.settings.client_secret:
                data["client_secret"] = self.settings.client_secret
            async with self._client(5.0) as client:
                await client.post(endpoint, data=data)
        except (httpx.HTTPError, UnauthorizedError) as exc:
            # Revocation is best-effort over network; local revocation is already recorded
            logger.debug("Remote revocation request failed: %s", type(exc).__name__)

    async def health(self) -> dict[str, Any]:
        """Health status: probes discovery, degraded when the provider is unreachable."""
        try:
            await self.discovery()
            status = "healthy"
        except UnauthorizedError:
            status = "degraded"
        else:
            if self._discovery_doc is None:
                # Development fallback served instead of a real discovery document.
                status = "degraded"
        return {"status": status, "provider": "oidc", "issuer": self.settings.issuer}
