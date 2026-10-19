# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""`docker compose config` checks of the backup overlays (PR #294 review, ASVS V14.1.1).

The backup credentials have no built-in defaults: rendering without them must fail, so a deployment
can never encrypt real backups with a passphrase published in this repository. Only renders the
configuration; skipped when the Docker CLI with the compose plugin is not installed.

Run: make test-scripts
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parent.parent.parent / "deploy"
REQUIRED = ("BACKUP_CIPHER_PASS", "BACKUP_S3_KEY", "BACKUP_S3_SECRET")
# compose.backup.yml is an overlay (its service depends on postgres): render it on the minimal profile.
FILES = {
    "compose.backup.yml": ("compose.minimal.yml", "compose.backup.yml"),
    "compose.backup-test.yml": ("compose.backup-test.yml",),
}


def _config(compose_file: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    if shutil.which("docker") is None:
        pytest.skip("docker CLI not installed")
    clean = {k: v for k, v in os.environ.items() if k not in REQUIRED}
    files = [arg for name in FILES[compose_file] for arg in ("-f", str(DEPLOY / name))]
    done = subprocess.run(
        ["docker", "compose", *files, "config", "--quiet"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env={**clean, **env},
    )
    if done.returncode != 0 and "is not a docker command" in done.stderr:
        pytest.skip("docker compose plugin not installed")
    return done


@pytest.mark.parametrize("compose_file", ["compose.backup.yml", "compose.backup-test.yml"])
@pytest.mark.parametrize("missing", REQUIRED)
def test_backup_credentials_have_no_default(compose_file: str, missing: str) -> None:
    values = {name: f"value-for-{name.lower()}" for name in REQUIRED if name != missing}
    done = _config(compose_file, values)
    if missing == "BACKUP_CIPHER_PASS" and compose_file == "compose.backup-test.yml":
        assert done.returncode == 0, done.stderr  # the test object store does not use the passphrase
        return
    assert done.returncode != 0
    assert missing in done.stderr


@pytest.mark.parametrize("compose_file", ["compose.backup.yml", "compose.backup-test.yml"])
def test_backup_overlay_renders_when_every_credential_is_set(compose_file: str) -> None:
    done = _config(compose_file, {name: f"value-for-{name.lower()}" for name in REQUIRED})
    assert done.returncode == 0, done.stderr


def test_restore_exec_reads_the_config_the_daemon_renders() -> None:
    """PR #356 review: `docker compose exec backup pgbackrest restore` (scripts/restore.sh) runs
    outside the daemon's process, so the rendered config's path must be in the service's own env."""
    if shutil.which("docker") is None:
        pytest.skip("docker CLI not installed")
    files = [arg for name in FILES["compose.backup.yml"] for arg in ("-f", str(DEPLOY / name))]
    done = subprocess.run(
        ["docker", "compose", *files, "config", "--format", "json"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env={**os.environ, **dict.fromkeys(REQUIRED, "set-for-test")},
    )
    if done.returncode != 0 and "is not a docker command" in done.stderr:
        pytest.skip("docker compose plugin not installed")
    assert done.returncode == 0, done.stderr
    env = json.loads(done.stdout)["services"]["backup"]["environment"]
    daemon = (DEPLOY / "backup" / "backup-daemon.sh").read_text(encoding="utf-8")
    assert env["PGBACKREST_CONFIG"] == "/tmp/pgbackrest.conf"
    assert 'PGBACKREST_CONFIG="${PGBACKREST_CONFIG:-/tmp/pgbackrest.conf}"' in daemon
