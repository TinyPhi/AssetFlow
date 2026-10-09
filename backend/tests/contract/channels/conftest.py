# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Shared fixtures for the channel contract suite (§C8.4)."""

from __future__ import annotations

import base64
import os
from pathlib import Path

import pytest

from app.channels.credentials import ChannelCredentialStore
from app.channels.runtime import ChannelRuntime
from app.providers.context import ProviderContext
from app.providers.secrets.file import FileSecretsProvider


@pytest.fixture
def secrets_provider(tmp_path: Path) -> FileSecretsProvider:
    root = tmp_path / "secrets"
    (root / "transit").mkdir(parents=True)
    (root / "transit" / "file.key").write_bytes(base64.b64encode(os.urandom(32)))
    context = ProviderContext(env="test", pillar="secrets", base_dir=tmp_path)
    return FileSecretsProvider.from_settings(
        {"directory": "secrets", "encryption_key_file": "transit/file.key"}, context
    )


@pytest.fixture
def store(secrets_provider: FileSecretsProvider) -> ChannelCredentialStore:
    return ChannelCredentialStore(secrets_provider)


@pytest.fixture
def runtime(store: ChannelCredentialStore) -> ChannelRuntime:
    return ChannelRuntime(store)
