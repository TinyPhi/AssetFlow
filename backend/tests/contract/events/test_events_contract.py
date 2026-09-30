# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""EventBusProvider contract suite (§B6.1 rule 2). Every implementation is added to IMPLEMENTATIONS."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from app.providers.context import ProviderContext
from app.providers.events.base import EventBusProvider
from app.providers.events.inmemory import InMemoryEventBusProvider

ORG = "0192f000-0000-7000-8000-000000000001"


def ctx() -> ProviderContext:
    return ProviderContext(env="test", pillar="events", base_dir=Path.cwd())


IMPLEMENTATIONS: list[tuple[str, Callable[[], EventBusProvider]]] = [
    ("inmemory", lambda: InMemoryEventBusProvider.from_settings({}, ctx())),
]


@pytest.fixture(params=IMPLEMENTATIONS, ids=[i[0] for i in IMPLEMENTATIONS])
def bus(request: pytest.FixtureRequest) -> EventBusProvider:
    factory: Callable[[], EventBusProvider] = request.param[1]
    return factory()


async def test_interface_version(bus: EventBusProvider) -> None:
    assert isinstance(bus, EventBusProvider)
    assert bus.INTERFACE_VERSION == "1.0"


async def test_publish_reaches_subscriber_with_organization(bus: EventBusProvider) -> None:
    received: list[dict[str, Any]] = []

    async def handler(envelope: dict[str, Any]) -> None:
        received.append(envelope)

    await bus.subscribe("asset.created", handler)
    await bus.publish("asset.created", {"asset_id": "a-1"}, ORG)
    await bus.publish("asset.retired", {"asset_id": "a-1"}, ORG)
    assert len(received) == 1
    assert received[0]["organization_id"] == ORG
    assert received[0]["payload"] == {"asset_id": "a-1"}


async def test_group_delivers_once_per_group(bus: EventBusProvider) -> None:
    calls: list[str] = []

    def make(tag: str) -> Callable[[dict[str, Any]], Any]:
        async def handler(envelope: dict[str, Any]) -> None:
            calls.append(tag)

        return handler

    await bus.subscribe("t", make("a1"), group="a")
    await bus.subscribe("t", make("a2"), group="a")
    await bus.subscribe("t", make("b1"), group="b")
    await bus.publish("t", {}, ORG)
    await bus.publish("t", {}, ORG)
    assert sorted(c for c in calls if c.startswith("a")) == ["a1", "a2"]
    assert calls.count("b1") == 2


async def test_organization_is_required(bus: EventBusProvider) -> None:
    with pytest.raises(ValueError, match="organization_id"):
        await bus.publish("t", {}, "")


async def test_failing_handler_is_logged_and_reported(
    bus: EventBusProvider, caplog: pytest.LogCaptureFixture
) -> None:
    received: list[dict[str, Any]] = []

    async def broken(envelope: dict[str, Any]) -> None:
        raise RuntimeError("handler bug")

    async def healthy(envelope: dict[str, Any]) -> None:
        received.append(envelope)

    await bus.subscribe("t", broken, group="broken")
    await bus.subscribe("t", healthy, group="healthy")
    with caplog.at_level(logging.ERROR):
        await bus.publish("t", {"n": 1}, ORG)

    assert len(received) == 1  # other groups still receive the event
    assert "event handler failed" in caplog.text
    assert "handler bug" in caplog.text  # traceback is logged, not swallowed
    health = await bus.health()
    assert health["status"] == "degraded"
    assert health["handler_failures"] == 1


async def test_health(bus: EventBusProvider) -> None:
    assert (await bus.health())["status"] in {"healthy", "degraded", "unhealthy"}
