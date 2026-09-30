# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for OpenBao Secrets Provider (§B6.1, §B6.2, M1.3-T9)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import ConfigError
from app.core.problems import SecretsUnavailableError
from app.providers.context import ProviderContext
from app.providers.secrets.openbao import OpenBaoSecretsProvider


async def test_openbao_invalid_ref() -> None:
    ctx = ProviderContext(env="test", pillar="secrets", base_dir=Path.cwd())
    provider = OpenBaoSecretsProvider.from_settings({"address": "http://localhost:8200"}, ctx)

    with pytest.raises(SecretsUnavailableError, match="Invalid secret reference"):
        await provider.get("invalid_ref")

    with pytest.raises(SecretsUnavailableError, match="Malformed path"):
        await provider.get_map("not_a_secret_uri")


def test_openbao_production_guards() -> None:
    ctx = ProviderContext(env="production", pillar="secrets", base_dir=Path.cwd())
    # Should fail if address is not HTTPS
    with pytest.raises(ConfigError) as exc_info:
        OpenBaoSecretsProvider.from_settings({"address": "http://localhost:8200"}, ctx)
    assert "address must use HTTPS in production" in str(exc_info.value)


async def test_openbao_health() -> None:
    ctx = ProviderContext(env="test", pillar="secrets", base_dir=Path.cwd())
    provider = OpenBaoSecretsProvider.from_settings({"address": "http://localhost:8200"}, ctx)
    health = await provider.health()
    assert health["provider"] == "openbao"
