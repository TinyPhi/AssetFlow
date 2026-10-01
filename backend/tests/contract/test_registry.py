# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Provider registry: config alone selects providers, entry-point discovery, secrets, health (§B6.1)."""

from __future__ import annotations

import secrets as pysecrets
import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from app.core.config import AppConfig, ConfigError, load_config
from app.core.problems import SecretsUnavailableError
from app.providers.auth.mock import MockAuthProvider
from app.providers.auth.oidc import OidcAuthProvider
from app.providers.events.inmemory import InMemoryEventBusProvider
from app.providers.events.postgres import PostgresEventBusProvider
from app.providers.registry import ProviderRegistry
from app.providers.secrets.file import FileSecretsProvider
from app.providers.secrets.openbao import OpenBaoSecretsProvider
from app.providers.telemetry.noop import NoOpTelemetryProvider
from app.providers.telemetry.otel import OtelTelemetryProvider

DATABASE = """
database:
  host: localhost
  name: assetflow
  api: {user: assetflow_api, password: "secret://database/api#password"}
  worker: {user: assetflow_worker, password: "secret://database/worker#password"}
  migrator: {user: assetflow_migrator, password: "secret://database/migrator#password"}
"""


def config(tmp_path: Path, providers: str, env: str = "test") -> AppConfig:
    text = f"env: {env}\nproviders:\n{textwrap.indent(textwrap.dedent(providers), '  ')}{DATABASE}"
    path = tmp_path / "assetflow.yaml"
    path.write_text(text, encoding="utf-8")
    return load_config(path)


FULL = """
auth: {type: mock}
secrets: {type: file, settings: {directory: secrets}}
telemetry: {type: noop}
events: {type: inmemory}
"""


def paths(exc: pytest.ExceptionInfo[ConfigError]) -> list[str]:
    return [p for p, _ in exc.value.errors]


def test_config_selects_builtin_providers(tmp_path: Path) -> None:
    registry = ProviderRegistry.from_config(config(tmp_path, FULL))
    assert isinstance(registry.auth, MockAuthProvider)
    assert isinstance(registry.secrets, FileSecretsProvider)
    assert isinstance(registry.telemetry, NoOpTelemetryProvider)
    assert isinstance(registry.events, InMemoryEventBusProvider)
    assert registry.types == {"auth": "mock", "secrets": "file", "telemetry": "noop", "events": "inmemory"}


def test_config_selects_production_providers(tmp_path: Path) -> None:
    prod_providers = """
    auth: {type: oidc, settings: {issuer: "http://localhost:8080", client_id: "assetflow"}}
    secrets: {type: openbao, settings: {address: "http://localhost:8200"}}
    telemetry: {type: otel, settings: {endpoint: "http://localhost:4317"}}
    events: {type: postgres, settings: {notify_channel: "outbox_events"}}
    """
    registry = ProviderRegistry.from_config(config(tmp_path, prod_providers))
    assert isinstance(registry.auth, OidcAuthProvider)
    assert isinstance(registry.secrets, OpenBaoSecretsProvider)
    assert isinstance(registry.telemetry, OtelTelemetryProvider)
    assert isinstance(registry.events, PostgresEventBusProvider)
    assert registry.types == {"auth": "oidc", "secrets": "openbao", "telemetry": "otel", "events": "postgres"}


def test_unknown_type_names_path(tmp_path: Path) -> None:
    cfg = config(tmp_path, FULL.replace("telemetry: {type: noop}", "telemetry: {type: nope}"))
    with pytest.raises(ConfigError) as exc:
        ProviderRegistry.from_config(cfg)
    assert paths(exc) == ["providers.telemetry.type"]
    assert "unknown provider 'nope'" in str(exc.value)


def test_bad_settings_name_path(tmp_path: Path) -> None:
    cfg = config(tmp_path, FULL.replace("{directory: secrets}", "{directory: secrets, bogus: 1}"))
    with pytest.raises(ConfigError) as exc:
        ProviderRegistry.from_config(cfg)
    assert paths(exc) == ["providers.secrets.settings.bogus"]


# ---------------------------------------------------------------------- external entry points

DUMMY_MODULE = """
from typing import Any
from app.providers.telemetry.noop import NoOpTelemetryProvider


class DummyTelemetry(NoOpTelemetryProvider):
    def __init__(self, settings: dict[str, Any]) -> None:
        self.settings = settings

    @classmethod
    def from_settings(cls, settings: dict[str, Any], context: Any) -> "DummyTelemetry":
        return cls(settings)


class NotAProvider:
    def __init__(self, settings: dict[str, Any], context: Any) -> None:
        pass
"""


@pytest.fixture
def external_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Install a fake third-party package (module plus dist-info entry points) on sys.path."""
    site = tmp_path / "site"
    site.mkdir()
    module = f"af_dummy_{pysecrets.token_hex(4)}"
    (site / f"{module}.py").write_text(DUMMY_MODULE, encoding="utf-8")
    dist = site / "af_dummy-0.1.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text("Metadata-Version: 2.1\nName: af-dummy\nVersion: 0.1\n", encoding="utf-8")
    (dist / "entry_points.txt").write_text(
        "[assetflow.providers.telemetry]\n"
        f"dummy = {module}:DummyTelemetry\n"
        f"broken = {module}:NotAProvider\n"
        f"missing = {module}:DoesNotExist\n"
        f"noop = {module}:DummyTelemetry\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(site))
    yield site
    sys.modules.pop(module, None)


def test_external_provider_selected_by_config(tmp_path: Path, external_package: Path) -> None:
    cfg = config(
        tmp_path, FULL.replace("telemetry: {type: noop}", "telemetry: {type: dummy, settings: {a: 1}}")
    )
    registry = ProviderRegistry.from_config(cfg)
    assert type(registry.telemetry).__name__ == "DummyTelemetry"
    assert registry.telemetry.settings == {"a": 1}  # type: ignore[attr-defined]
    assert registry.types["telemetry"] == "dummy"


def test_external_provider_listed_when_unknown(tmp_path: Path, external_package: Path) -> None:
    cfg = config(tmp_path, FULL.replace("telemetry: {type: noop}", "telemetry: {type: other}"))
    with pytest.raises(ConfigError, match="dummy"):
        ProviderRegistry.from_config(cfg)


def test_external_wrong_interface_is_refused(tmp_path: Path, external_package: Path) -> None:
    cfg = config(tmp_path, FULL.replace("telemetry: {type: noop}", "telemetry: {type: broken}"))
    with pytest.raises(ConfigError) as exc:
        ProviderRegistry.from_config(cfg)
    assert paths(exc) == ["providers.telemetry.type"]
    assert "does not implement TelemetryProvider" in str(exc.value)


def test_external_unloadable_is_refused(tmp_path: Path, external_package: Path) -> None:
    cfg = config(tmp_path, FULL.replace("telemetry: {type: noop}", "telemetry: {type: missing}"))
    with pytest.raises(ConfigError, match="cannot be loaded"):
        ProviderRegistry.from_config(cfg)


def test_builtin_name_cannot_be_hijacked(tmp_path: Path, external_package: Path) -> None:
    registry = ProviderRegistry.from_config(config(tmp_path, FULL))
    assert type(registry.telemetry) is NoOpTelemetryProvider


# ------------------------------------------------------------------------------ resolve_secret


async def test_resolve_secret_reads_provider(tmp_path: Path) -> None:
    value = pysecrets.token_urlsafe(24)
    folder = tmp_path / "secrets" / "database" / "api"
    folder.mkdir(parents=True)
    (folder / "password").write_text(value, encoding="utf-8")
    registry = ProviderRegistry.from_config(config(tmp_path, FULL))
    assert await registry.resolve_secret("secret://database/api#password") == value


async def test_resolve_secret_missing_raises(tmp_path: Path) -> None:
    (tmp_path / "secrets").mkdir()
    registry = ProviderRegistry.from_config(config(tmp_path, FULL))
    with pytest.raises(SecretsUnavailableError):
        await registry.resolve_secret("secret://database/api#password")
    with pytest.raises(SecretsUnavailableError):
        await registry.resolve_secret("secret://malformed")


async def test_resolve_secret_env_value_outside_production(tmp_path: Path) -> None:
    registry = ProviderRegistry.from_config(config(tmp_path, FULL))
    value = pysecrets.token_hex(8)
    assert await registry.resolve_secret(value) == value
    with pytest.raises(SecretsUnavailableError):
        await registry.resolve_secret("")


async def test_resolve_secret_refuses_values_in_production(tmp_path: Path) -> None:
    base = ProviderRegistry.from_config(config(tmp_path, FULL))
    registry = ProviderRegistry(base.auth, base.secrets, base.telemetry, base.events, env="production")
    with pytest.raises(SecretsUnavailableError):
        await registry.resolve_secret(pysecrets.token_hex(8))


# ------------------------------------------------------------------------------------- health


async def test_health_aggregates(tmp_path: Path) -> None:
    (tmp_path / "secrets").mkdir()
    registry = ProviderRegistry.from_config(config(tmp_path, FULL))
    health = await registry.health()
    assert health["status"] == "healthy"
    assert set(health["providers"]) == {"auth", "secrets", "telemetry", "events"}


async def test_health_hides_exception_text(tmp_path: Path) -> None:
    (tmp_path / "secrets").mkdir()
    registry = ProviderRegistry.from_config(config(tmp_path, FULL))

    leaked = pysecrets.token_hex(8)

    async def exploding() -> dict[str, Any]:
        raise RuntimeError(f"detail {leaked} at /internal/path")

    registry.events.health = exploding  # type: ignore[method-assign]
    health = await registry.health()
    assert health["status"] == "unhealthy"
    assert health["providers"]["events"] == {"status": "unhealthy", "provider": "inmemory"}
    assert leaked not in repr(health)
    assert "/internal/path" not in repr(health)


async def test_health_degraded_and_invalid_results(tmp_path: Path) -> None:
    registry = ProviderRegistry.from_config(config(tmp_path, FULL))  # secrets dir absent -> unhealthy
    assert (await registry.health())["status"] == "unhealthy"

    (tmp_path / "secrets").mkdir()

    async def degraded() -> dict[str, Any]:
        return {"status": "degraded"}

    registry.telemetry.health = degraded  # type: ignore[method-assign]
    assert (await registry.health())["status"] == "degraded"

    async def nonsense() -> dict[str, Any]:
        return {"status": "fine"}

    registry.telemetry.health = nonsense  # type: ignore[method-assign]
    assert (await registry.health())["status"] == "unhealthy"
