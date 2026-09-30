# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""AuthProvider contract suite (§B6.1 rule 2). Every auth implementation is added to IMPLEMENTATIONS."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from app.core.config import ConfigError
from app.core.problems import UnauthorizedError
from app.providers.auth.base import AuthProvider, Principal
from app.providers.auth.mock import MockAuthProvider
from app.providers.context import ProviderContext

ORG = "0192f000-0000-7000-8000-000000000001"


def ctx(env: str = "test") -> ProviderContext:
    return ProviderContext(env=env, pillar="auth", base_dir=Path.cwd())  # type: ignore[arg-type]


# Each entry: (name, factory, token_for(subject, organization_id, roles | None) -> str)
Factory = Callable[[], AuthProvider]
TokenFor = Callable[[str, str, list[str] | None], str]


def _mock_token(subject: str, organization_id: str, roles: list[str] | None) -> str:
    claims: dict[str, object] = {"sub": subject, "organization_id": organization_id}
    if roles is not None:
        claims["roles"] = roles
    return json.dumps(claims)


IMPLEMENTATIONS: list[tuple[str, Factory, TokenFor]] = [
    ("mock", lambda: MockAuthProvider.from_settings({}, ctx()), _mock_token),
]


@pytest.fixture(params=IMPLEMENTATIONS, ids=[i[0] for i in IMPLEMENTATIONS])
def impl(request: pytest.FixtureRequest) -> tuple[AuthProvider, TokenFor]:
    _, factory, token_for = request.param
    return factory(), token_for


async def test_interface_version(impl: tuple[AuthProvider, TokenFor]) -> None:
    provider, _ = impl
    assert isinstance(provider, AuthProvider)
    assert provider.INTERFACE_VERSION == "1.0"


async def test_valid_token(impl: tuple[AuthProvider, TokenFor]) -> None:
    provider, token_for = impl
    principal = await provider.verify_token(token_for("user-1", ORG, ["viewer"]))
    assert isinstance(principal, Principal)
    assert principal.subject == "user-1"
    assert principal.organization_id == ORG
    assert principal.roles == ["viewer"]


async def test_roles_default_to_none(impl: tuple[AuthProvider, TokenFor]) -> None:
    provider, token_for = impl
    principal = await provider.verify_token(token_for("user-1", ORG, None))
    assert principal.roles == []


@pytest.mark.parametrize(
    "token",
    [
        "",
        "test-token",
        "not json {",
        "[]",
        "{}",
        '{"sub": "user-1"}',
        '{"organization_id": "org"}',
        '{"sub": "", "organization_id": "org"}',
        '{"sub": "user-1", "organization_id": "org", "roles": "admin"}',
        '{"sub": "user-1", "organization_id": "org", "roles": [1]}',
        '{"sub": 5, "organization_id": "org"}',
    ],
)
async def test_malformed_tokens_are_unauthorized(impl: tuple[AuthProvider, TokenFor], token: str) -> None:
    provider, _ = impl
    with pytest.raises(UnauthorizedError):
        await provider.verify_token(token)


async def test_revoked_token_is_unauthorized(impl: tuple[AuthProvider, TokenFor]) -> None:
    provider, token_for = impl
    token = token_for("user-1", ORG, ["viewer"])
    await provider.revoke(token)
    with pytest.raises(UnauthorizedError):
        await provider.verify_token(token)


async def test_code_exchange_refresh_and_revoke(impl: tuple[AuthProvider, TokenFor]) -> None:
    provider, _ = impl
    tokens = await provider.exchange_code("code-1", redirect_uri="http://localhost/cb")
    assert {"access_token", "refresh_token", "token_type", "expires_in"} <= tokens.keys()

    rotated = await provider.refresh(tokens["refresh_token"])
    assert rotated["refresh_token"] != tokens["refresh_token"]
    with pytest.raises(UnauthorizedError):
        await provider.refresh(tokens["refresh_token"])  # rotated away

    await provider.revoke(rotated["refresh_token"])
    with pytest.raises(UnauthorizedError):
        await provider.refresh(rotated["refresh_token"])


async def test_unknown_refresh_token_is_unauthorized(impl: tuple[AuthProvider, TokenFor]) -> None:
    provider, _ = impl
    with pytest.raises(UnauthorizedError):
        await provider.refresh("never-issued")


async def test_discovery(impl: tuple[AuthProvider, TokenFor]) -> None:
    provider, _ = impl
    doc = await provider.discovery()
    assert {"issuer", "token_endpoint", "jwks_uri"} <= doc.keys()


async def test_health(impl: tuple[AuthProvider, TokenFor]) -> None:
    provider, _ = impl
    assert (await provider.health())["status"] in {"healthy", "degraded", "unhealthy"}


def test_mock_refused_in_production() -> None:
    with pytest.raises(ConfigError) as exc:
        MockAuthProvider.from_settings({}, ctx("production"))
    assert exc.value.errors[0][0] == "providers.auth.type"


def test_mock_rejects_unknown_settings() -> None:
    with pytest.raises(ConfigError) as exc:
        MockAuthProvider.from_settings({"default_role": "admin"}, ctx())
    assert exc.value.errors[0][0] == "providers.auth.settings.default_role"
