# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Worker process helpers: heartbeat and worker id (§B9.3). No database, no network."""

from __future__ import annotations

import os
import time
from pathlib import Path

from workers.main import heartbeat_is_fresh, worker_id


def test_heartbeat_freshness(tmp_path: Path) -> None:
    beat = tmp_path / "heartbeat"
    assert not heartbeat_is_fresh(beat)
    beat.touch()
    assert heartbeat_is_fresh(beat)
    old = time.time() - 120
    os.utime(beat, (old, old))
    assert not heartbeat_is_fresh(beat)


def test_worker_id_is_host_and_pid_only() -> None:
    assert worker_id().endswith(f"-{os.getpid()}")
