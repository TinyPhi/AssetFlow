# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Unit tests for restore scripts and restore drill safety (§B11.4, §B13.5, M1.6-T9)."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

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
    assert "docker compose -p assetflow down" not in content


# ------------------------------------------------------------- restore drill result (PR #356 review)

BASH = shutil.which("bash") or "bash"  # the PATH's bash (on Windows, not System32's WSL launcher)


def _stub(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8", newline="\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _drill(tmp_path: Path, *, docker: str = "exit 0\n", canary: str = "exit 0\n") -> tuple[int, dict]:
    """Run restore-test.sh with `docker` and the canary's Python replaced by stubs."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub(bin_dir, "docker", docker)
    _stub(bin_dir, "python3", canary)
    result = tmp_path / "result.json"
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    env["RESTORE_TEST_RESULT_FILE"] = result.as_posix()
    done = subprocess.run(
        [BASH, RESTORE_TEST_SH.as_posix()],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return done.returncode, json.loads(result.read_text(encoding="utf-8"))


pytestmark_drill = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


@pytestmark_drill
def test_a_passing_drill_records_success_and_a_measured_rto(tmp_path: Path) -> None:
    code, result = _drill(tmp_path, docker="sleep 1\n")
    assert code == 0
    assert result["status"] == "success"
    assert result["canary_status"] == "passed"
    assert result["failed_steps"] == []
    assert result["rto_seconds"] >= 2  # two docker calls of a second each: measured, not a constant


@pytestmark_drill
def test_a_failed_canary_fails_the_drill(tmp_path: Path) -> None:
    code, result = _drill(tmp_path, canary="exit 1\n")
    assert code != 0
    assert result["status"] == "failed"
    assert result["canary_status"] == "failed"
    assert result["failed_steps"] == ["canary"]


@pytestmark_drill
def test_an_environment_that_does_not_start_fails_the_drill(tmp_path: Path) -> None:
    code, result = _drill(tmp_path, docker="exit 1\n")
    assert code != 0
    assert result["status"] == "failed"
    assert "environment" in result["failed_steps"]
    assert "migrate" in result["failed_steps"]


# ---------------------------------------------------------- restore.sh fails loudly (PR #356 review)


def _sh_path(path: Path) -> str:
    """A path for the scripts' `tar`: Git for Windows' tar reads `C:` as a remote host name."""
    posix = path.as_posix()
    if sys.platform == "win32" and len(posix) > 1 and posix[1] == ":":
        return f"/{posix[0].lower()}{posix[2:]}"
    return posix


def _restore(tmp_path: Path, *, docker: str, canary: str = "exit 0\n") -> subprocess.CompletedProcess[str]:
    """Run restore.sh with a real keys archive, and `docker` and the canary's Python stubbed."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub(bin_dir, "docker", docker)
    _stub(bin_dir, "python3", canary)
    keys = tmp_path / "keys.tar.gz"
    (tmp_path / "transit").mkdir()
    (tmp_path / "transit" / "key").write_text("placeholder", encoding="utf-8")
    with tarfile.open(keys, "w:gz") as archive:
        archive.add(tmp_path / "transit", arcname="transit")
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    env["RESTORE_SECRETS_DIR"] = (tmp_path / "secrets").as_posix()
    return subprocess.run(
        [BASH, RESTORE_SH.as_posix(), "--keys", _sh_path(keys)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@pytestmark_drill
def test_a_restore_where_every_step_works_reports_success(tmp_path: Path) -> None:
    done = _restore(tmp_path, docker="exit 0\n")
    assert done.returncode == 0, done.stderr
    assert "Restore completed successfully!" in done.stdout


@pytestmark_drill
def test_a_failed_pgbackrest_restore_stops_with_an_error(tmp_path: Path) -> None:
    done = _restore(tmp_path, docker='case " $* " in *" exec "*) exit 1 ;; esac\nexit 0\n')
    assert done.returncode != 0
    assert "pgBackRest restore failed" in done.stderr
    assert "Restore completed successfully" not in done.stdout


@pytestmark_drill
def test_a_failed_canary_fails_the_restore(tmp_path: Path) -> None:
    done = _restore(tmp_path, docker="exit 0\n", canary="exit 1\n")
    assert done.returncode != 0
    assert "canary check failed" in done.stderr
    assert "Restore completed successfully" not in done.stdout


@pytestmark_drill
def test_a_keys_archive_that_cannot_be_extracted_stops_the_restore(tmp_path: Path) -> None:
    bad = tmp_path / "not-an-archive.tar.gz"
    bad.write_text("not a tar file", encoding="utf-8")
    env = {**os.environ, "RESTORE_SECRETS_DIR": (tmp_path / "secrets").as_posix()}
    done = subprocess.run(
        [BASH, RESTORE_SH.as_posix(), "--keys", _sh_path(bad)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode != 0
    assert "could not extract the keys archive" in done.stderr
