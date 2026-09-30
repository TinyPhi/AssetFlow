# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for OIDC Auth Provider with Zitadel preset (§B5.5, §B6.2, M1.3-T8)."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.core.problems import UnauthorizedError
from app.providers.auth.oidc import OidcAuthProvider
from app.providers.context import ProviderContext

ORG_ID = "0192f000-0000-7000-8000-000000000001"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


@pytest.fixture
def rsa_key_pair() -> tuple[rsa.RSAPrivateKey, dict[str, str]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_numbers = private_key.public_key().public_numbers()
    n_b64 = b64url(public_numbers.n.to_bytes((public_numbers.n.bit_length() + 7) // 8, "big"))
    e_b64 = b64url(public_numbers.e.to_bytes((public_numbers.e.bit_length() + 7) // 8, "big"))
    jwk = {"kty": "RSA", "kid": "test-key-1", "use": "sig", "alg": "RS256", "n": n_b64, "e": e_b64}
    return private_key, jwk


def sign_jwt(payload: dict[str, object], private_key: rsa.RSAPrivateKey, kid: str = "test-key-1") -> str:
    header = {"alg": "RS256", "typ": "JWT", "kid": kid}
    header_b64 = b64url(json.dumps(header).encode("utf-8"))
    payload_b64 = b64url(json.dumps(payload).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    sig_b64 = b64url(signature)
    return f"{header_b64}.{payload_b64}.{sig_b64}"


async def test_oidc_zitadel_token_verification(
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, str]],
) -> None:
    priv_key, jwk = rsa_key_pair
    ctx = ProviderContext(env="test", pillar="auth", base_dir=Path.cwd())
    provider = OidcAuthProvider.from_settings(
        {
            "issuer": "http://localhost:8080",
            "client_id": "assetflow",
        },
        ctx,
    )
    # Inject JWKS for offline verification in tests
    provider._jwks = {"keys": [jwk]}

    future_exp = int((datetime.now(UTC) + timedelta(hours=1)).timestamp())
    claims = {
        "sub": "user-zitadel-1",
        "email": "user@example.org",
        "name": "Acme User",
        "exp": future_exp,
        "urn:zitadel:iam:user:resourceowner:id": ORG_ID,
        "urn:zitadel:iam:org:project:roles": {"asset_manager": {ORG_ID: "Acme"}},
    }
    token = sign_jwt(claims, priv_key)

    principal = await provider.verify_token(token)
    assert principal.subject == "user-zitadel-1"
    assert principal.organization_id == ORG_ID
    assert principal.roles == ["asset_manager"]
    assert principal.email == "user@example.org"
    assert principal.name == "Acme User"


async def test_oidc_expired_token(rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, str]]) -> None:
    priv_key, jwk = rsa_key_pair
    ctx = ProviderContext(env="test", pillar="auth", base_dir=Path.cwd())
    provider = OidcAuthProvider.from_settings(
        {"issuer": "http://localhost:8080", "client_id": "assetflow"}, ctx
    )
    provider._jwks = {"keys": [jwk]}

    past_exp = int((datetime.now(UTC) - timedelta(hours=1)).timestamp())
    claims = {
        "sub": "user-2",
        "exp": past_exp,
        "urn:zitadel:iam:user:resourceowner:id": ORG_ID,
    }
    token = sign_jwt(claims, priv_key)

    with pytest.raises(UnauthorizedError, match="expired"):
        await provider.verify_token(token)


async def test_oidc_revocation(rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, str]]) -> None:
    priv_key, jwk = rsa_key_pair
    ctx = ProviderContext(env="test", pillar="auth", base_dir=Path.cwd())
    provider = OidcAuthProvider.from_settings(
        {"issuer": "http://localhost:8080", "client_id": "assetflow"}, ctx
    )
    provider._jwks = {"keys": [jwk]}

    claims = {"sub": "user-3", "urn:zitadel:iam:user:resourceowner:id": ORG_ID}
    token = sign_jwt(claims, priv_key)

    await provider.revoke(token)
    with pytest.raises(UnauthorizedError):
        await provider.verify_token(token)


async def test_oidc_health() -> None:
    ctx = ProviderContext(env="test", pillar="auth", base_dir=Path.cwd())
    provider = OidcAuthProvider.from_settings(
        {"issuer": "http://localhost:8080", "client_id": "assetflow"}, ctx
    )
    health = await provider.health()
    assert health["status"] == "healthy"
    assert health["provider"] == "oidc"
