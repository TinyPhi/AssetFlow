# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The file secrets provider logs a missing secret without its name or reserved LogRecord keys.

NEW-4: `name` collides with the reserved `LogRecord.name` attribute. A later CodeQL finding showed
logging the secret's name at all is unnecessary (its area is enough to locate it); only the area is
logged now.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from app.core.problems import SecretsUnavailableError
from app.providers.context import ProviderContext
from app.providers.secrets.file import FileSecretsProvider


async def test_a_missing_secret_logs_and_raises_the_domain_error(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    provider = FileSecretsProvider(ProviderContext(env="test", pillar="secrets", base_dir=tmp_path), tmp_path)
    with caplog.at_level(logging.WARNING, logger="app.providers.secrets.file"):
        with pytest.raises(SecretsUnavailableError):
            await provider.get("secret://area/missing#key")
        with pytest.raises(SecretsUnavailableError):
            await provider.get_map("secret://area/missing")
    records = [r for r in caplog.records if r.getMessage() == "secrets.file.missing"]
    assert len(records) == 2
    assert all(r.area == "area" for r in records)
    assert all(not hasattr(r, "key_name") and not hasattr(r, "secret_name") for r in records)
