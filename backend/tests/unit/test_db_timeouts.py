# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Unit tests for pool creation and acquire timeouts (AF-009, AF-018; §B10)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import pytest

from app.core import db
from app.core.db import DatabaseUnavailableError, init_pool, platform_transaction, tenant_transaction
from app.core.problems import ServiceUnavailableError


@dataclass(frozen=True)
class _Role:
    user: str = "u"
    password: str = "p"


@dataclass(frozen=True)
class _Cfg:
    host: str = "127.0.0.1"
    port: int = 1  # nothing listens here
    name: str = "x"
    api: _Role = _Role()
    worker: _Role = _Role()
    migrator: _Role = _Role()
    behind_pgbouncer: bool = False
    statement_timeout_ms: int = 1000
    idle_in_transaction_timeout_ms: int = 1000
    pool_min: int = 1
    pool_max: int = 1
    connect_timeout_s: float = 2.0
    acquire_timeout_s: float = 0.05


async def _resolve(_ref: str) -> str:
    raise AssertionError("literal password expected")


async def test_unreachable_database_raises_clean_error_and_logs(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("ERROR", logger="app.core.db"), pytest.raises(DatabaseUnavailableError):
        await init_pool(_Cfg(), "api", _resolve)
    assert any(r.message == "db.unreachable" for r in caplog.records)


class _TimingOutAcquire:
    async def __aenter__(self) -> Any:
        raise TimeoutError

    async def __aexit__(self, *_exc: object) -> None:
        raise AssertionError("nothing was acquired")


class _TimingOutPool:
    def __init__(self) -> None:
        self.timeouts: list[float] = []

    def acquire(self, *, timeout: float) -> _TimingOutAcquire:
        self.timeouts.append(timeout)
        return _TimingOutAcquire()


async def test_acquire_timeout_is_a_503_in_tenant_and_platform_transactions() -> None:
    pool: Any = _TimingOutPool()
    db._ACQUIRE_TIMEOUT[id(pool)] = (pool, 0.25)
    try:
        with pytest.raises(ServiceUnavailableError) as tenant:
            async with tenant_transaction(pool, uuid4()):
                pass
        with pytest.raises(ServiceUnavailableError):
            async with platform_transaction(pool):
                pass
    finally:
        del db._ACQUIRE_TIMEOUT[id(pool)]
    assert tenant.value.status_code == 503
    assert pool.timeouts == [0.25, 0.25]
