# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The postgres events provider NOTIFYs an opaque wake-up id, never tenant data (AF-008)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.providers.context import ProviderContext
from app.providers.events import postgres as postgres_module
from app.providers.events.postgres import PostgresEventBusProvider

ORG_ID = "0192f000-0000-7000-8000-000000000001"


class _Conn:
    def __init__(self, sent: list[tuple[Any, ...]]) -> None:
        self.sent = sent

    async def execute(self, *args: Any) -> None:
        self.sent.append(args)


class _Acquire:
    def __init__(self, conn: _Conn) -> None:
        self.conn = conn

    async def __aenter__(self) -> _Conn:
        return self.conn

    async def __aexit__(self, *exc: object) -> None:
        return None


class _Pool:
    def __init__(self) -> None:
        self.sent: list[tuple[Any, ...]] = []

    def acquire(self) -> _Acquire:
        return _Acquire(_Conn(self.sent))


async def test_notify_payload_carries_no_tenant_data(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = _Pool()
    monkeypatch.setattr(postgres_module, "get_db_pool", lambda: pool)
    ctx = ProviderContext(env="test", pillar="events", base_dir=Path.cwd())
    provider = PostgresEventBusProvider.from_settings({}, ctx)

    await provider.publish("asset.created", {"event_id": "evt-1", "asset_tag": "LAPTOP-7"}, ORG_ID)

    assert len(pool.sent) == 1
    _sql, channel, payload = pool.sent[0]
    assert channel == "outbox_events"
    for tenant_data in (ORG_ID, "asset.created", "evt-1", "LAPTOP-7"):
        assert tenant_data not in payload
    assert len(payload) == 32
    int(payload, 16)


async def test_event_provider_has_default_aclose() -> None:
    ctx = ProviderContext(env="test", pillar="events", base_dir=Path.cwd())
    await PostgresEventBusProvider.from_settings({}, ctx).aclose()
