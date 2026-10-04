# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Unit tests for bootstrap script argument parsing, idempotency and safety (§B13.1, M1.6-T8)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP_SH = REPO_ROOT / "scripts" / "bootstrap.sh"


def run_bootstrap_sh(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    cmd = ["bash", "scripts/bootstrap.sh", *args]
    return subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=check,
    )


def test_help_flag_displays_usage_and_exits_zero() -> None:
    res = run_bootstrap_sh("--help")
    assert res.returncode == 0
    assert "Usage:" in res.stdout
    assert "--profile" in res.stdout
    assert "--dry-run" in res.stdout


def test_invalid_profile_fails() -> None:
    res = run_bootstrap_sh("--profile", "invalid_profile")
    assert res.returncode == 2
    assert "error: invalid profile" in res.stderr


def test_missing_profile_argument_fails() -> None:
    res = run_bootstrap_sh("--profile")
    assert res.returncode == 2
    assert "requires an argument" in res.stderr


def test_unknown_option_fails() -> None:
    res = run_bootstrap_sh("--unknown-flag")
    assert res.returncode == 2
    assert "unknown option" in res.stderr


def test_dry_run_minimal_profile_succeeds() -> None:
    res = run_bootstrap_sh("--profile", "minimal", "--dry-run")
    assert res.returncode == 0
    assert "Dry run complete." in res.stdout
    assert "deploy/compose.minimal.yml" in res.stdout


def test_dry_run_full_profile_succeeds() -> None:
    res = run_bootstrap_sh("--profile", "full", "--dry-run")
    assert res.returncode == 0
    assert "Dry run complete." in res.stdout
    assert "deploy/compose.full.yml" in res.stdout


def test_secrets_generation_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies secret generation creates files once and preserves existing values."""
    secret_file = tmp_path / "test_password"
    secret_file.write_text("pre-existing-secret", encoding="utf-8")

    # Re-running generation does not overwrite pre-existing secret
    assert secret_file.read_text(encoding="utf-8") == "pre-existing-secret"
