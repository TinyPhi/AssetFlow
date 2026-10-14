# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The worker process exits cleanly when the database is unreachable at boot (AF-009)."""

from __future__ import annotations

from typing import Any

import pytest

from app.core.db import DatabaseUnavailableError


async def test_worker_exits_with_status_1_when_database_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    from workers import main as worker_main  # noqa: PLC0415

    async def unreachable(*_args: Any, **_kwargs: Any) -> None:
        raise DatabaseUnavailableError("database is unreachable")

    class _Providers:
        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(worker_main, "load_config", lambda _path: object())
    monkeypatch.setattr(worker_main.ProviderRegistry, "from_config", lambda _cfg: _Providers())
    monkeypatch.setattr(worker_main, "serve", unreachable)
    monkeypatch.setattr(worker_main, "_install_signal_handlers", lambda _stop: None)
    assert await worker_main.run(None) == 1
