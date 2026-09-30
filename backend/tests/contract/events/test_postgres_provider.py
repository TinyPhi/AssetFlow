# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for PostgreSQL transactional outbox event bus provider (§B6.1, §B6.2, M1.3-T11)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.providers.context import ProviderContext
from app.providers.events.postgres import PostgresEventBusProvider

ORG_ID = "0192f000-0000-7000-8000-000000000001"


async def test_postgres_events_requires_organization_id() -> None:
    ctx = ProviderContext(env="test", pillar="events", base_dir=Path.cwd())
    provider = PostgresEventBusProvider.from_settings({}, ctx)

    with pytest.raises(ValueError, match="organization_id is required"):
        await provider.publish("asset.assigned", {"asset_id": "1"}, organization_id="")


async def test_postgres_events_pub_sub_local_dispatch() -> None:
    ctx = ProviderContext(env="test", pillar="events", base_dir=Path.cwd())
    provider = PostgresEventBusProvider.from_settings({}, ctx)

    received_g1: list[dict[str, object]] = []
    received_g2: list[dict[str, object]] = []

    async def handler_g1(envelope: dict[str, object]) -> None:
        received_g1.append(envelope)

    async def handler_g2(envelope: dict[str, object]) -> None:
        received_g2.append(envelope)

    await provider.subscribe("asset.created", handler_g1, group="group_audit")
    await provider.subscribe("asset.created", handler_g2, group="group_notifications")

    payload = {"event_id": "evt-1", "asset_id": "0192f000-0000-7000-8000-000000000010"}
    await provider.publish("asset.created", payload, organization_id=ORG_ID)

    assert len(received_g1) == 1
    assert len(received_g2) == 1
    assert received_g1[0]["organization_id"] == ORG_ID
    assert received_g1[0]["topic"] == "asset.created"
    assert received_g1[0]["payload"] == payload

    health = await provider.health()
    assert health["status"] == "healthy"
    assert health["provider"] == "postgres"
    assert health["published"] == 1
