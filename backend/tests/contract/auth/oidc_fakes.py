# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""A fake OIDC identity provider behind an httpx MockTransport, for offline provider tests."""

from __future__ import annotations

import base64
import json
import secrets
import time
from urllib.parse import parse_qs

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

ISSUER = "https://idp.example.test"
CLIENT_ID = "assetflow"
KID = "test-key-1"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def make_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwk_for(key: rsa.RSAPrivateKey, kid: str = KID) -> dict[str, str]:
    nums = key.public_key().public_numbers()
    return {
        "kty": "RSA",
        "kid": kid,
        "use": "sig",
        "alg": "RS256",
        "n": b64url(nums.n.to_bytes((nums.n.bit_length() + 7) // 8, "big")),
        "e": b64url(nums.e.to_bytes((nums.e.bit_length() + 7) // 8, "big")),
    }


def sign_jwt(
    payload: dict[str, object],
    key: rsa.RSAPrivateKey,
    kid: str = KID,
    alg: str = "RS256",
) -> str:
    header = {"alg": alg, "typ": "JWT", "kid": kid}
    head = b64url(json.dumps(header).encode())
    body = b64url(json.dumps(payload).encode())
    signature = key.sign(f"{head}.{body}".encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
    return f"{head}.{body}.{b64url(signature)}"


def good_claims(subject: str, org_id: str, roles: list[str] | None, **extra: object) -> dict[str, object]:
    claims: dict[str, object] = {
        "sub": subject,
        "iss": ISSUER,
        "aud": [CLIENT_ID],
        "iat": int(time.time()) - 5,
        "exp": int(time.time()) + 300,
        "urn:zitadel:iam:user:resourceowner:id": org_id,
    }
    if roles is not None:
        claims["urn:zitadel:iam:org:project:roles"] = {r: {org_id: "Org"} for r in roles}
    claims.update(extra)
    return claims


class FakeIdp:
    """Serves discovery, JWKS, token (code and refresh grants, rotating) and revocation."""

    def __init__(
        self,
        key: rsa.RSAPrivateKey,
        issuer: str = ISSUER,
        discovery_issuer: str | None = None,
        discovery_status: int = 200,
    ) -> None:
        self.key = key
        self.issuer = issuer
        self.discovery_issuer = discovery_issuer or issuer
        self.discovery_status = discovery_status
        self.requests: list[str] = []
        self.revoke_bodies: list[dict[str, str]] = []
        self._refresh_tokens: set[str] = set()

    def _issue(self) -> dict[str, object]:
        refresh = secrets.token_urlsafe(16)
        self._refresh_tokens.add(refresh)
        return {
            "access_token": secrets.token_urlsafe(16),
            "refresh_token": refresh,
            "token_type": "Bearer",
            "expires_in": 300,
        }

    def handle(self, request: httpx.Request) -> httpx.Response:  # noqa: PLR0911 - a route table
        path = request.url.path
        self.requests.append(path)
        if path.endswith("/.well-known/openid-configuration"):
            if self.discovery_status != 200:
                return httpx.Response(self.discovery_status)
            return httpx.Response(
                200,
                json={
                    "issuer": self.discovery_issuer,
                    "jwks_uri": f"{self.issuer}/oauth/v2/keys",
                    "token_endpoint": f"{self.issuer}/oauth/v2/token",
                    "revocation_endpoint": f"{self.issuer}/oauth/v2/revoke",
                },
            )
        if path.endswith("/oauth/v2/keys"):
            return httpx.Response(200, json={"keys": [jwk_for(self.key)]})
        if path.endswith("/oauth/v2/token"):
            form = parse_qs(request.content.decode())
            if form.get("grant_type") == ["authorization_code"]:
                return httpx.Response(200, json=self._issue())
            old = (form.get("refresh_token") or [""])[0]
            if old in self._refresh_tokens:
                self._refresh_tokens.discard(old)
                return httpx.Response(200, json=self._issue())
            return httpx.Response(400, json={"error": "invalid_grant"})
        if path.endswith("/oauth/v2/revoke"):
            form = parse_qs(request.content.decode())
            self.revoke_bodies.append({k: v[0] for k, v in form.items()})
            return httpx.Response(200)
        return httpx.Response(404)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)
