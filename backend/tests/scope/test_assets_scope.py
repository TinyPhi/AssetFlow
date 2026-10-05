# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Scope handling for the asset API (§B5.3, M2.1-T5, P8-07).

Part a covers create/edit/detail scope behavior; list-based scope scenarios (sibling org units in
one list call, team-holder visibility in a page, "matches two branches appears once", revoked grant
stops at the next list request) are added here in part b, once `GET /api/v1/assets` exists.
"""

from __future__ import annotations

from pathlib import Path

from app.providers.auth.mock import MockAuthProvider
from app.providers.context import ProviderContext
from app.providers.secrets.file import FileSecretsProvider
from app.providers.telemetry.noop import NoOpTelemetryProvider

BASE = "/api/v1/assets"


class _Registry:
    def __init__(self, secrets: FileSecretsProvider) -> None:
        self.auth = MockAuthProvider(ProviderContext("test", "auth", Path()))
        self.telemetry = NoOpTelemetryProvider()
        self.secrets = secrets
