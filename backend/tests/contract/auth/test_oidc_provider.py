# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for OIDC Auth Provider with Zitadel preset (§B5.5, §B6.2, M1.3-T8; audit AF-001..AF-039)."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import httpx
import oidc_fakes
import pytest
from oidc_fakes import FakeIdp, b64url, good_claims, sign_jwt

from app.core.config import ConfigError
from app.core.problems import SecretsUnavailableError, UnauthorizedError
from app.providers.auth.oidc import OidcAuthProvider, OidcAuthSettings
from app.providers.context import ProviderContext

ORG_ID = "0192f000-0000-7000-8000-000000000001"
OTHER_ORG = "0192f000-0000-7000-8000-000000000002"
KEY = oidc_fakes.make_key()
ORG_CLAIM = "urn:zitadel:iam:user:resourceowner:id"
ROLES_CLAIM = "urn:zitadel:iam:org:project:roles"


def make(
    env: str = "test",
    idp: FakeIdp | None = None,
    **settings: Any,
) -> tuple[OidcAuthProvider, FakeIdp]:
    idp = idp or FakeIdp(KEY)
    cfg = {
        "issuer": oidc_fakes.ISSUER,
        "client_id": oidc_fakes.CLIENT_ID,
        "audience": "assetflow",
        **settings,
    }
    ctx = ProviderContext(env=env, pillar="auth", base_dir=Path.cwd())  # type: ignore[arg-type]
    return OidcAuthProvider(OidcAuthSettings(**cfg), ctx, transport=idp.transport()), idp


async def test_zitadel_token_verification() -> None:
    provider, _ = make()
    token = sign_jwt(
        good_claims("user-zitadel-1", ORG_ID, ["asset_manager"], email="user@example.org", name="Acme User"),
        KEY,
    )
    principal = await provider.verify_token(token)
    assert principal.subject == "user-zitadel-1"
    assert principal.organization_id == ORG_ID
    assert principal.roles == ["asset_manager"]
    assert principal.email == "user@example.org"
    assert principal.name == "Acme User"


async def test_expired_token() -> None:
    provider, _ = make()
    token = sign_jwt(good_claims("u", ORG_ID, None, exp=int(time.time()) - 3600), KEY)
    with pytest.raises(UnauthorizedError, match="expired"):
        await provider.verify_token(token)


async def test_revocation() -> None:
    provider, _ = make()
    token = sign_jwt(good_claims("u", ORG_ID, None), KEY)
    await provider.verify_token(token)
    await provider.revoke(token)
    with pytest.raises(UnauthorizedError):
        await provider.verify_token(token)


# AF-001: an empty key set refuses; the signature is always checked.
async def test_empty_jwks_is_unauthorized() -> None:
    provider, idp = make()
    provider._jwks = {"keys": []}
    provider._jwks_fetched_at = time.monotonic()

    def empty(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"keys": []})

    provider._transport = httpx.MockTransport(
        lambda r: empty(r) if r.url.path.endswith("/keys") else idp.handle(r)
    )
    token = sign_jwt(good_claims("u", ORG_ID, None), KEY)
    with pytest.raises(UnauthorizedError):
        await provider.verify_token(token)


async def test_wrong_signing_key_is_unauthorized() -> None:
    provider, _ = make()
    token = sign_jwt(good_claims("u", ORG_ID, None), oidc_fakes.make_key())
    with pytest.raises(UnauthorizedError):
        await provider.verify_token(token)


# AF-021 negative suite: alg=none, HS256, missing exp.
def _unsigned(alg: str, claims: dict[str, object]) -> str:
    head = b64url(json.dumps({"alg": alg, "typ": "JWT", "kid": oidc_fakes.KID}).encode())
    return f"{head}.{b64url(json.dumps(claims).encode())}.{b64url(b'forged')}"


@pytest.mark.parametrize("alg", ["none", "None", "HS256", "HS512", "ES256"])
async def test_forbidden_algorithms_are_unauthorized(alg: str) -> None:
    provider, _ = make()
    with pytest.raises(UnauthorizedError):
        await provider.verify_token(_unsigned(alg, good_claims("u", ORG_ID, ["admin"])))


async def test_missing_alg_is_unauthorized() -> None:
    provider, _ = make()
    head = b64url(json.dumps({"typ": "JWT", "kid": oidc_fakes.KID}).encode())
    body = b64url(json.dumps(good_claims("u", ORG_ID, None)).encode())
    with pytest.raises(UnauthorizedError):
        await provider.verify_token(f"{head}.{body}.{b64url(b'x')}")


async def test_missing_exp_is_unauthorized() -> None:
    provider, _ = make()
    claims = good_claims("u", ORG_ID, None)
    del claims["exp"]
    with pytest.raises(UnauthorizedError):
        await provider.verify_token(sign_jwt(claims, KEY))


# AF-002: iss, aud, nbf/iat.
async def test_wrong_issuer_is_unauthorized() -> None:
    provider, _ = make()
    token = sign_jwt(good_claims("u", ORG_ID, None, iss="https://evil.example.test"), KEY)
    with pytest.raises(UnauthorizedError):
        await provider.verify_token(token)


async def test_missing_issuer_is_unauthorized() -> None:
    provider, _ = make()
    claims = good_claims("u", ORG_ID, None)
    del claims["iss"]
    with pytest.raises(UnauthorizedError):
        await provider.verify_token(sign_jwt(claims, KEY))


@pytest.mark.parametrize("aud", ["someone-else", ["someone-else"], [], None])
async def test_wrong_audience_is_unauthorized(aud: object) -> None:
    provider, _ = make()
    claims = good_claims("u", ORG_ID, None)
    claims["aud"] = aud
    with pytest.raises(UnauthorizedError):
        await provider.verify_token(sign_jwt(claims, KEY))


async def test_audience_string_or_list_containing_it_is_accepted() -> None:
    provider, _ = make()
    for aud in ("assetflow", ["x", "assetflow"]):
        claims = good_claims("u", ORG_ID, None)
        claims["aud"] = aud
        assert (await provider.verify_token(sign_jwt(claims, KEY))).subject == "u"


async def test_future_nbf_is_unauthorized_and_small_skew_tolerated() -> None:
    provider, _ = make()
    far = sign_jwt(good_claims("u", ORG_ID, None, nbf=int(time.time()) + 600), KEY)
    with pytest.raises(UnauthorizedError):
        await provider.verify_token(far)
    near = sign_jwt(good_claims("u", ORG_ID, None, nbf=int(time.time()) + 30), KEY)
    assert (await provider.verify_token(near)).subject == "u"


async def test_future_iat_is_unauthorized() -> None:
    provider, _ = make()
    token = sign_jwt(good_claims("u", ORG_ID, None, iat=int(time.time()) + 600), KEY)
    with pytest.raises(UnauthorizedError):
        await provider.verify_token(token)


@pytest.mark.parametrize("env", ["staging", "production"])
def test_audience_required_outside_development_and_test(env: str) -> None:
    with pytest.raises(ConfigError) as exc:
        make(env=env, audience=None, issuer="https://idp.example.test")
    assert any(path == "providers.auth.settings.audience" for path, _ in exc.value.errors)


# AF-003: https and discovery issuer.
def test_http_issuer_refused_outside_development_and_test() -> None:
    with pytest.raises(ConfigError) as exc:
        make(env="staging", issuer="http://idp.example.test")
    assert any(path == "providers.auth.settings.issuer" for path, _ in exc.value.errors)


async def test_mismatched_discovery_issuer_is_refused() -> None:
    provider, _ = make(idp=FakeIdp(KEY, discovery_issuer="https://other.example.test"))
    with pytest.raises(UnauthorizedError):
        await provider.discovery()
    token = sign_jwt(good_claims("u", ORG_ID, None), KEY)
    with pytest.raises(UnauthorizedError):
        await provider.verify_token(token)


async def test_no_silent_discovery_fallback_outside_development() -> None:
    provider, _ = make(idp=FakeIdp(KEY, discovery_status=503))
    with pytest.raises(UnauthorizedError):
        await provider.discovery()


async def test_discovery_fallback_only_in_development() -> None:
    provider, _ = make(env="development", idp=FakeIdp(KEY, discovery_status=503))
    assert (await provider.discovery())["issuer"] == oidc_fakes.ISSUER


# AF-011: roles only from the token's own organization.
async def test_role_from_other_org_is_ignored() -> None:
    provider, _ = make()
    claims = good_claims("u", ORG_ID, None)
    claims[ROLES_CLAIM] = {"admin": {OTHER_ORG: "Other"}, "viewer": {ORG_ID: "Mine", OTHER_ORG: "Other"}}
    principal = await provider.verify_token(sign_jwt(claims, KEY))
    assert principal.roles == ["viewer"]


async def test_generic_claim_fallbacks_dropped_outside_development() -> None:
    provider, _ = make()
    claims = good_claims("u", ORG_ID, None)
    del claims[ORG_CLAIM]
    claims["org_id"] = ORG_ID
    with pytest.raises(UnauthorizedError):
        await provider.verify_token(sign_jwt(claims, KEY))

    claims = good_claims("u", ORG_ID, None)
    claims["roles"] = ["admin"]
    assert (await provider.verify_token(sign_jwt(claims, KEY))).roles == []


async def test_generic_claim_fallbacks_allowed_in_development() -> None:
    provider, _ = make(env="development")
    claims = good_claims("u", ORG_ID, None)
    del claims[ORG_CLAIM]
    claims["org_id"] = ORG_ID
    claims["roles"] = ["admin"]
    principal = await provider.verify_token(sign_jwt(claims, KEY))
    assert principal.organization_id == ORG_ID
    assert principal.roles == ["admin"]


# AF-012: revocation set is capped (LRU).
async def test_revocation_set_is_capped() -> None:
    provider, _ = make(revocation_cache_size=3)
    for i in range(10):
        await provider.revoke(f"token-{i}")
    assert len(provider._revoked) == 3
    assert list(provider._revoked) == ["token-7", "token-8", "token-9"]


# AF-024: health probes discovery.
async def test_health_healthy_when_discovery_reachable() -> None:
    provider, _ = make()
    health = await provider.health()
    assert health["status"] == "healthy"
    assert health["provider"] == "oidc"


async def test_health_degraded_when_discovery_unreachable() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    provider, _ = make()
    provider._transport = httpx.MockTransport(boom)
    assert (await provider.health())["status"] == "degraded"


# AF-039: single-flight discovery and JWKS; failed discovery cached briefly.
async def test_concurrent_verifications_fetch_discovery_and_jwks_once() -> None:
    provider, idp = make()
    tokens = [sign_jwt(good_claims(f"u{i}", ORG_ID, None), KEY) for i in range(8)]
    results = await asyncio.gather(*(provider.verify_token(t) for t in tokens))
    assert len(results) == 8
    assert sum(p.endswith("openid-configuration") for p in idp.requests) == 1
    assert sum(p.endswith("/oauth/v2/keys") for p in idp.requests) == 1


async def test_failed_discovery_is_cached_briefly() -> None:
    provider, idp = make(idp=FakeIdp(KEY, discovery_status=503))
    for _ in range(3):
        with pytest.raises(UnauthorizedError):
            await provider.discovery()
    assert sum(p.endswith("openid-configuration") for p in idp.requests) == 1


async def test_client_secret_reference_is_resolved_through_the_secrets_provider() -> None:
    """AF-015: a `secret://` client secret is resolved, never sent as the literal reference."""
    provider, _ = make(client_secret="secret://oidc/web#client_secret")
    seen: list[str] = []

    async def resolver(ref: str) -> str:
        seen.append(ref)
        return "resolved-value"

    provider.secret_resolver = resolver
    assert await provider._client_secret() == "resolved-value"
    assert seen == ["secret://oidc/web#client_secret"]


async def test_client_secret_reference_without_a_resolver_is_unavailable() -> None:
    provider, _ = make(client_secret="secret://oidc/web#client_secret")
    with pytest.raises(SecretsUnavailableError):
        await provider._client_secret()
