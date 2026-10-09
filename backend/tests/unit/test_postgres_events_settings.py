# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Defaults of the postgres events provider settings."""

from __future__ import annotations

from app.providers.events.postgres import PostgresEventsSettings


def test_poll_interval_defaults_to_two_seconds() -> None:
    assert PostgresEventsSettings().poll_interval_seconds == 2.0
