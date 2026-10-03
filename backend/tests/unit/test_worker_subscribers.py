# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Subscriber registry (§B6.2). No database, no network."""

from __future__ import annotations

import pytest

from workers.subscribers import SubscriberRegistry, default_registry


def test_registry_refuses_a_second_subscription_with_the_same_consumer_name() -> None:
    async def handler(conn: object, event: object) -> None:
        return None

    registry = SubscriberRegistry()
    registry.subscribe("item.created", "consumer", handler)  # type: ignore[arg-type]
    assert [s.consumer for s in registry.for_event("item.created")] == ["consumer"]
    assert registry.for_event("other") == []
    with pytest.raises(ValueError, match="already subscribed"):
        registry.subscribe("item.created", "consumer", handler)  # type: ignore[arg-type]


def test_default_registry_starts_empty() -> None:
    assert default_registry().for_event("anything") == []
