# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Environment policy of the HTTP layer: cookie key (NEW-1), CORS origins (AF-023), docs and mock
routes (AF-033, NEW-3). Unit tests: no database, network or file system."""

from __future__ import annotations

import secrets
from types import SimpleNamespace
from typing import Any

import pytest

from app.api import policy
from app.core.config import ConfigError
from app.core.cookie_crypto import derive_key
from app.main import Bootstrap, create_app

KEY_REF = "secret://session/cookie#key"


def _config(env: str, **extra: Any) -> SimpleNamespace:
    platform = SimpleNamespace(allowed_origins=extra.pop("origins", []))
    providers = SimpleNamespace(auth=SimpleNamespace(type=extra.pop("auth", "mock")))
    return SimpleNamespace(env=env, platform=platform, providers=providers, **extra)


def _resolver(value: str) -> Any:
    async def resolve(ref: str) -> str:
        assert ref == KEY_REF
        return value

    return resolve


async def _no_resolver(ref: str) -> str:
    raise AssertionError("no secret should be resolved")


@pytest.mark.parametrize("env", ["staging", "production", "", "prod"])
async def test_cookie_key_is_required_outside_development_and_test(env: str) -> None:
    with pytest.raises(ConfigError, match="session_cookie_key"):
        await policy.session_cookie_key(_config(env), _no_resolver)


@pytest.mark.parametrize("env", ["development", "test"])
async def test_cookie_key_is_random_per_process_in_development_and_test(env: str) -> None:
    first = await policy.session_cookie_key(_config(env), _no_resolver)
    second = await policy.session_cookie_key(_config(env), _no_resolver)
    assert len(first) == 32
    assert first != second
    assert first != derive_key("assetflow_dev_cookie_secret_key_32_bytes!")


async def test_cookie_key_comes_from_the_secret_reference() -> None:
    value = secrets.token_urlsafe(48)
    key = await policy.session_cookie_key(_config("production", session_cookie_key=KEY_REF), _resolver(value))
    assert key == derive_key(value)


async def test_cookie_key_must_be_a_secret_reference() -> None:
    with pytest.raises(ConfigError, match="secret://"):
        await policy.session_cookie_key(
            _config("development", session_cookie_key=secrets.token_urlsafe(48)), _no_resolver
        )


async def test_short_cookie_key_secret_is_refused() -> None:
    with pytest.raises(ConfigError, match="at least"):
        await policy.session_cookie_key(
            _config("production", session_cookie_key=KEY_REF), _resolver(secrets.token_hex(4))
        )


def test_wildcard_origin_is_refused_outside_development_and_test() -> None:
    for env in ("production", "staging"):
        with pytest.raises(ConfigError, match="allowed_origins"):
            policy.allowed_origins(_config(env, origins=["https://app.example.org", "*"]))
    assert policy.allowed_origins(_config("development", origins=["*"])) == ["*"]


def test_origins_come_from_platform_allowed_origins() -> None:
    origins = ["https://a.example.org", " https://b.example.org "]
    assert policy.allowed_origins(_config("production", origins=origins)) == [
        "https://a.example.org",
        "https://b.example.org",
    ]


@pytest.mark.parametrize(
    ("env", "auth", "expected"),
    [
        ("development", "mock", True),
        ("test", "mock", True),
        ("development", "oidc", False),
        ("staging", "mock", False),
        ("production", "mock", False),
        ("", "mock", False),
    ],
)
def test_mock_routes_only_for_mock_auth_in_development_or_test(env: str, auth: str, expected: bool) -> None:
    assert policy.mock_auth_enabled(_config(env, auth=auth)) is expected


def test_unknown_environment_counts_as_production() -> None:
    assert policy.environment(SimpleNamespace()) == "production"
    assert policy.docs_enabled(SimpleNamespace()) is False


def _bootstrap(config: Any) -> Bootstrap:
    class Registry:
        closed = False

        async def resolve_secret(self, ref: str) -> str:
            return secrets.token_urlsafe(48)

        async def aclose(self) -> None:
            Registry.closed = True

    registry = Registry()

    async def open_pool(cfg: Any, resolve: Any) -> object:
        return object()

    async def close_pool(pool: Any) -> None:
        return None

    return Bootstrap(
        load_config=lambda: config,
        build_registry=lambda cfg: registry,
        open_pool=open_pool,
        close_pool=close_pool,
    )


async def test_boot_refuses_production_without_a_cookie_key() -> None:
    bootstrap = _bootstrap(_config("production", auth="oidc"))
    app = create_app(bootstrap=bootstrap)
    with pytest.raises(ConfigError, match="session_cookie_key"):
        async with app.router.lifespan_context(app):
            pytest.fail("boot must be refused")
    assert getattr(app.state, "pool", None) is None


async def test_boot_refuses_a_wildcard_origin_in_production() -> None:
    config = _config("production", auth="oidc", origins=["*"], session_cookie_key=KEY_REF)
    app = create_app(bootstrap=_bootstrap(config))
    with pytest.raises(ConfigError, match="allowed_origins"):
        async with app.router.lifespan_context(app):
            pytest.fail("boot must be refused")


async def test_boot_publishes_the_derived_cookie_key() -> None:
    config = _config("production", auth="oidc", session_cookie_key=KEY_REF)
    app = create_app(bootstrap=_bootstrap(config))
    async with app.router.lifespan_context(app):
        assert len(app.state.session_cookie_key) == 32
