# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The config validate CLI's domain-template check (needs modules.domain_template_check)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import main
from tests.unit.test_config import base, write


def test_cli_valid(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", str(write(tmp_path, base()))]) == 0
    assert "config valid" in capsys.readouterr().out
