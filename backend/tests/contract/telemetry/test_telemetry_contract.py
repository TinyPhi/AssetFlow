# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""TelemetryProvider contract suite (§B6.1 rule 2). Every implementation is added to IMPLEMENTATIONS."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import pytest

from app.core.config import ConfigError
from app.providers.context import ProviderContext
from app.providers.telemetry.base import TelemetryProvider
from app.providers.telemetry.noop import NoOpTelemetryProvider


def ctx() -> ProviderContext:
    return ProviderContext(env="test", pillar="telemetry", base_dir=Path.cwd())


IMPLEMENTATIONS: list[tuple[str, Callable[[], TelemetryProvider]]] = [
    ("noop", lambda: NoOpTelemetryProvider.from_settings({}, ctx())),
]


@pytest.fixture(params=IMPLEMENTATIONS, ids=[i[0] for i in IMPLEMENTATIONS])
def provider(request: pytest.FixtureRequest) -> TelemetryProvider:
    factory: Callable[[], TelemetryProvider] = request.param[1]
    return factory()


async def test_interface_version(provider: TelemetryProvider) -> None:
    assert isinstance(provider, TelemetryProvider)
    assert provider.INTERFACE_VERSION == "1.0"


async def test_operations_never_raise(provider: TelemetryProvider) -> None:
    provider.init(object())
    provider.record_metric("assetflow_http_requests_total", 1.0, {"route": "/api/health"})
    provider.capture_exception(RuntimeError("boom"), {"where": "contract"})
    with provider.start_span("service.contract.run", {"k": "v"}) as span:
        span.set_attribute("key", "value")
    assert isinstance(provider.logger, logging.Logger)


async def test_health(provider: TelemetryProvider) -> None:
    assert (await provider.health())["status"] in {"healthy", "degraded", "unhealthy"}


def test_noop_rejects_unknown_settings() -> None:
    with pytest.raises(ConfigError) as exc:
        NoOpTelemetryProvider.from_settings({"endpoint": "x"}, ctx())
    assert exc.value.errors[0][0] == "providers.telemetry.settings.endpoint"
