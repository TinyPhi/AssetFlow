# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Worker settings (§B9.3, §C4.7). No database, no network."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import WorkersConfig


def test_workers_defaults_match_the_plan() -> None:
    cfg = WorkersConfig()
    assert cfg.outbox.batch_size == 50
    assert cfg.outbox.poll_interval_seconds == 2
    assert cfg.outbox.reclaim_after_seconds == 300
    assert cfg.outbox.max_attempts == 5


@pytest.mark.parametrize(
    "field", ["batch_size", "poll_interval_seconds", "reclaim_after_seconds", "max_attempts"]
)
def test_workers_outbox_rejects_non_positive_values(field: str) -> None:
    with pytest.raises(ValidationError):
        WorkersConfig.model_validate({"outbox": {field: 0}})


def test_workers_config_rejects_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        WorkersConfig.model_validate({"outbox": {"max_attempt": 3}})
