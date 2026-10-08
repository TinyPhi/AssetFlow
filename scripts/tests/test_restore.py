# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Unit tests for restore scripts and restore drill safety (§B11.4, §B13.5, M1.6-T9)."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RESTORE_SH = REPO_ROOT / "scripts" / "restore.sh"
RESTORE_TEST_SH = REPO_ROOT / "scripts" / "restore-test.sh"


def run_restore_sh(*args: str) -> subprocess.CompletedProcess[str]:
    cmd = ["bash", "scripts/restore.sh", *args]
    return subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_restore_help_flag_displays_usage_and_exits_zero() -> None:
    res = run_restore_sh("--help")
    assert res.returncode == 0
    assert "Usage:" in res.stdout
    assert "--keys" in res.stdout


def test_restore_refuses_execution_without_keys_archive() -> None:
    res = run_restore_sh()
    assert res.returncode == 2
    assert "error: missing required --keys argument" in res.stderr


def test_restore_fails_when_keys_archive_does_not_exist() -> None:
    res = run_restore_sh("--keys", "nonexistent-keys-file.tar.gz")
    assert res.returncode == 1
    assert "keys archive not found" in res.stderr


def test_restore_script_enforces_keys_before_database_order() -> None:
    content = RESTORE_SH.read_text(encoding="utf-8")
    keys_idx = content.find("Restoring cryptographic keys")
    db_idx = content.find("Restoring database")
    assert keys_idx != -1 and db_idx != -1
    assert keys_idx < db_idx, "Keys MUST be restored before database (§B11.4)"


def test_restore_test_cleans_up_only_its_own_project() -> None:
    content = RESTORE_TEST_SH.read_text(encoding="utf-8")
    assert 'TEST_PROJECT="assetflow-restoretest"' in content
    assert 'docker compose -p "${TEST_PROJECT}"' in content
    # Teardown trap must never delete main assetflow project
    assert 'docker compose -p assetflow down' not in content
