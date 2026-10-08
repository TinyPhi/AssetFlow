# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Health endpoints and application lifespan (§B6.1 rule 4, M1.3-T12).

The real app factory, middleware and handlers run over httpx's ASGI transport. The provider registry
and the database pool are small test doubles: these tests make no isolation or SQL claims, and the pool
double only answers the readiness probe (``SELECT 1``).
"""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.api.deps import require_platform_admin, require_principal
from app.core.config import load_config
from app.core.problems import SecretsUnavailableError
from app.main import Bootstrap, create_app

DB_SECRET_REF = "secret://database/api#password"

TEST_CONFIG_YAML = """env: test
platform:
  admins: []
providers:
  auth: {{type: mock, settings: {{}}}}
  secrets: {{type: file, settings: {{directory: "{secrets_dir}", allow_env: false}}}}
  telemetry: {{type: noop, settings: {{}}}}
  events: {{type: inmemory, settings: {{}}}}
database:
  host: localhost
  name: assetflow
  api: {{user: assetflow_api, password: "secret://database/api#password"}}
  worker: {{user: assetflow_worker, password: "secret://database/worker#password"}}
  migrator: {{user: assetflow_migrator, password: "secret://database/migrator#password"}}
"""


@dataclass
class FakeRegistry:
    """Stands in for ProviderRegistry: resolve_secret and health only."""

    secrets_by_ref: dict[str, str] = field(default_factory=dict)
    report: Mapping[str, Any] = field(
        default_factory=lambda: {
            "status": "healthy",
            "providers": {p: {"status": "healthy"} for p in ("auth", "secrets", "telemetry", "events")},
        }
    )
    health_error: Exception | None = None
    resolved: list[str] = field(default_factory=list)

    async def resolve_secret(self, ref: str) -> str:
        self.resolved.append(ref)
        try:
            return self.secrets_by_ref[ref]
        except KeyError:
            raise SecretsUnavailableError() from None

    async def health(self) -> Mapping[str, Any]:
        if self.health_error is not None:
            raise self.health_error
        return self.report


@dataclass
class FakePool:
    """Answers the readiness probe; can be told to fail like a lost database."""

    password: str
    error: Exception | None = None
    closed: bool = False
    queries: list[str] = field(default_factory=list)

    async def fetchval(self, query: str, *args: Any) -> Any:
        self.queries.append(query)
        if self.error is not None:
            raise self.error
        return 1


@dataclass
class Harness:
    app: FastAPI
    registry: FakeRegistry
    config: dict[str, Any]
    pools: list[FakePool] = field(default_factory=list)

    @property
    def pool(self) -> FakePool:
        return self.pools[-1]


def make_harness(registry: FakeRegistry | None = None) -> Harness:
    """Build the app with test doubles; the database password is random and generated at runtime."""
    reg = registry or FakeRegistry(secrets_by_ref={DB_SECRET_REF: secrets.token_urlsafe(24)})
    config: dict[str, Any] = {"env": "test", "database": {"api": {"password": DB_SECRET_REF}}}
    harness_pools: list[FakePool] = []

    async def open_pool(cfg: Any, resolve_secret: Any) -> FakePool:
        pool = FakePool(password=await resolve_secret(cfg["database"]["api"]["password"]))
        harness_pools.append(pool)
        return pool

    async def close_pool(pool: Any) -> None:
        pool.closed = True

    bootstrap = Bootstrap(
        load_config=lambda: config,
        build_registry=lambda _cfg: reg,
        open_pool=open_pool,
        close_pool=close_pool,
    )
    return Harness(app=create_app(bootstrap=bootstrap), registry=reg, config=config, pools=harness_pools)


@pytest.fixture
def harness() -> Harness:
    return make_harness()


@pytest.fixture
async def client(harness: Harness) -> AsyncIterator[httpx.AsyncClient]:
    """A client for an app whose lifespan (startup and shutdown) has run."""
    transport = httpx.ASGITransport(app=harness.app, raise_app_exceptions=False)
    async with (
        harness.app.router.lifespan_context(harness.app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as ac,
    ):
        yield ac


LEAKY_TEXT = "host=db.internal user=assetflow_api password=hunter2 /etc/assetflow"


async def test_liveness(client: httpx.AsyncClient) -> None:
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_readiness_ok_is_minimal(client: httpx.AsyncClient, harness: Harness) -> None:
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert resp.headers["cache-control"] == "no-store"
    assert harness.pool.queries == ["SELECT 1"]


async def test_readiness_503_when_database_fails(client: httpx.AsyncClient, harness: Harness) -> None:
    harness.pool.error = ConnectionError(LEAKY_TEXT)
    resp = await client.get("/api/health")
    assert resp.status_code == 503
    assert resp.json() == {"status": "unavailable"}
    assert "hunter2" not in resp.text


async def test_readiness_503_when_provider_unhealthy(client: httpx.AsyncClient, harness: Harness) -> None:
    harness.registry.report = {
        "status": "unhealthy",
        "providers": {
            "secrets": {"status": "unhealthy", "error": LEAKY_TEXT, "provider": "FileSecretsProvider"},
        },
    }
    resp = await client.get("/api/health")
    assert resp.status_code == 503
    assert resp.json() == {"status": "unavailable"}


async def test_readiness_503_when_registry_health_raises(client: httpx.AsyncClient, harness: Harness) -> None:
    harness.registry.health_error = RuntimeError(LEAKY_TEXT)
    resp = await client.get("/api/health")
    assert resp.status_code == 503
    assert resp.json() == {"status": "unavailable"}


async def test_provider_health_is_cached_for_five_seconds(
    client: httpx.AsyncClient, harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AF-038: provider health is probed once per 5 s window, then again after it."""
    from app.api import health as health_module  # noqa: PLC0415 - patching the module clock

    calls: list[int] = []
    original = harness.registry.health

    async def counting_health() -> Mapping[str, Any]:
        calls.append(1)
        return await original()

    harness.registry.health = counting_health  # type: ignore[method-assign]
    clock = [1000.0]
    monkeypatch.setattr(health_module.time, "monotonic", lambda: clock[0])

    for _ in range(3):
        assert (await client.get("/api/health")).status_code == 200
    assert len(calls) == 1

    clock[0] += health_module.PROVIDER_HEALTH_TTL_SECONDS + 0.1
    assert (await client.get("/api/health")).status_code == 200
    assert len(calls) == 2


async def test_public_readiness_is_rate_limited(client: httpx.AsyncClient) -> None:
    """AF-038: the unauthenticated readiness probe answers 429 with Retry-After past its limit."""
    from app.api.health import PUBLIC_HEALTH_LIMIT  # noqa: PLC0415

    for _ in range(PUBLIC_HEALTH_LIMIT):
        assert (await client.get("/api/health")).status_code == 200
    resp = await client.get("/api/health")
    assert resp.status_code == 429
    assert int(resp.headers["retry-after"]) >= 1
    assert (await client.get("/healthz")).status_code == 200


async def test_readiness_503_before_startup() -> None:
    """Without a completed lifespan there is no pool or registry: not ready."""
    harness = make_harness()
    transport = httpx.ASGITransport(app=harness.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/health")
    assert resp.status_code == 503
    assert resp.json() == {"status": "unavailable"}


async def test_provider_health_requires_platform_admin(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/health/providers")
    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.headers["www-authenticate"] == "Bearer"
    body = resp.json()
    assert body["code"] == "auth.unauthorized"
    assert "providers" not in body


async def test_provider_health_is_sanitized_for_admins(client: httpx.AsyncClient, harness: Harness) -> None:
    async def allow() -> None:
        return None

    harness.app.dependency_overrides[require_platform_admin] = allow
    harness.app.dependency_overrides[require_principal] = allow
    harness.registry.report = {
        "status": "degraded",
        "providers": {
            "auth": {"status": "healthy", "provider": "MockAuthProvider", "issuer": "http://idp.internal"},
            "secrets": {"status": "degraded", "error": LEAKY_TEXT, "path": "/run/secrets"},
            "telemetry": "weird-value",
        },
    }
    resp = await client.get("/api/health/providers")
    assert resp.status_code == 200
    assert resp.json() == {
        "status": "ok",
        "providers": {
            "auth": {"status": "healthy"},
            "secrets": {"status": "degraded"},
            "telemetry": {"status": "unknown"},
            "events": {"status": "unknown"},
        },
        "providers_overall": "degraded",
        "database": {"status": "healthy"},
    }
    for leak in ("hunter2", "Mock", "idp.internal", "/run/secrets", "env", "version"):
        assert leak not in resp.text


async def test_info_does_not_disclose_env_or_version(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/info")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["data"] == {"name": "AssetFlow", "api_version": "v1"}
    assert "test" not in resp.text.replace("request_id", "")
    assert "0.1.0" not in resp.text


async def test_ping_envelope(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/ping")
    body = resp.json()
    assert set(body) == {"status", "status_code", "message", "timestamp", "request_id", "data"}
    assert body["data"] == {"pong": True}
    assert body["request_id"] == resp.headers["x-request-id"]


async def test_lifespan_publishes_state_resolves_secret_and_closes_pool(harness: Harness) -> None:
    app = harness.app
    async with app.router.lifespan_context(app):
        assert app.state.config is harness.config
        assert app.state.registry is harness.registry
        assert app.state.pool is harness.pool
        assert harness.registry.resolved == [DB_SECRET_REF]
        assert harness.pool.password == harness.registry.secrets_by_ref[DB_SECRET_REF]
        assert harness.pool.closed is False
    assert harness.pool.closed is True
    assert app.state.pool is None


async def test_startup_fails_when_database_secret_is_missing() -> None:
    harness = make_harness(FakeRegistry(secrets_by_ref={}))
    with pytest.raises(SecretsUnavailableError):
        async with harness.app.router.lifespan_context(harness.app):
            pytest.fail("startup must not succeed without the database secret")
    assert harness.pools == []


def test_create_app_does_no_work() -> None:
    """Building the app must not load config or touch providers or the database."""
    calls: list[str] = []

    def load() -> object:
        calls.append("load_config")
        return {}

    create_app(bootstrap=Bootstrap(load_config=load))
    assert calls == []


async def test_real_config_and_registry_with_file_secrets(tmp_path: Path) -> None:
    """Real load_config and ProviderRegistry (mock auth, file secrets in a tmp dir); only the pool
    is a double. The database password comes from the secrets directory through the registry."""
    password = secrets.token_urlsafe(24)
    secrets_dir = tmp_path / "secrets"
    (secrets_dir / "database" / "api").mkdir(parents=True)
    (secrets_dir / "database" / "api" / "password").write_text(password, encoding="utf-8")
    config_file = tmp_path / "assetflow.yaml"
    config_file.write_text(TEST_CONFIG_YAML.format(secrets_dir=secrets_dir.as_posix()), encoding="utf-8")
    pools: list[FakePool] = []

    async def open_pool(cfg: Any, resolve_secret: Any) -> FakePool:
        pool = FakePool(password=await resolve_secret(cfg.database.api.password))
        pools.append(pool)
        return pool

    async def close_pool(pool: Any) -> None:
        pool.closed = True

    app = create_app(
        bootstrap=Bootstrap(
            load_config=lambda: load_config(config_file), open_pool=open_pool, close_pool=close_pool
        )
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as ac,
    ):
        assert app.state.config.env == "test"
        assert pools[0].password == password
        resp = await ac.get("/api/health")
        assert resp.json() == {"status": "ok"}
        assert resp.status_code == 200
    assert pools[0].closed is True
