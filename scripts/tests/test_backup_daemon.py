# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""deploy/backup/backup-daemon.sh renders its config and measures real metrics (PR #356 review).

pgBackRest reads its config literally, so the mounted template must be rendered before any call
(blocker 1), and the exported metrics must come from `pgbackrest info` and `pg_stat_archiver`, not
fixed numbers (blocker 3). `pgbackrest` and `psql` are replaced by stubs on PATH;
BACKUP_DAEMON_ONCE=1 makes the daemon render, measure once and exit.

Run: make test-scripts
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DAEMON = REPO_ROOT / "deploy" / "backup" / "backup-daemon.sh"
TEMPLATE = REPO_ROOT / "deploy" / "backup" / "pgbackrest.conf.template"
BASH = shutil.which("bash") or "bash"  # the PATH's bash (on Windows, not System32's WSL launcher)

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("envsubst") is None or shutil.which("jq") is None,
    reason="needs bash, envsubst and jq (all in the backup image)",
)


def _stub(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8", newline="\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _run(tmp_path: Path, *, info: object, archived: str, **env: str) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (tmp_path / "info.json").write_text(json.dumps(info), encoding="utf-8")
    _stub(bin_dir, "pgbackrest", f'cat "{(tmp_path / "info.json").as_posix()}"\n')
    _stub(bin_dir, "psql", f"echo '{archived}'\n" if archived else "exit 2\n")
    full_env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "PGBACKREST_TEMPLATE": TEMPLATE.as_posix(),
        "PGBACKREST_CONFIG": (tmp_path / "pgbackrest.conf").as_posix(),
        "BACKUP_METRICS_DIR": (tmp_path / "metrics").as_posix(),
        "BACKUP_DAEMON_ONCE": "1",
        "BACKUP_S3_KEY": "s3-access-id",
        "BACKUP_S3_SECRET": "s3-access-value",
        "BACKUP_CIPHER_PASS": "cipher-value",
        **env,
    }
    return subprocess.run(
        [BASH, DAEMON.as_posix()], env=full_env, capture_output=True, text=True, timeout=60, check=False
    )


def _metrics(tmp_path: Path) -> dict[str, float]:
    lines = (tmp_path / "metrics" / "backup.prom").read_text(encoding="utf-8").splitlines()
    return {k: float(v) for k, v in (line.split() for line in lines if line and not line.startswith("#"))}


def _info(*stops: int, delta: int = 1000) -> list[dict[str, object]]:
    backups = [
        {"timestamp": {"start": s - 60, "stop": s}, "info": {"repository": {"delta": delta}}} for s in stops
    ]
    return [{"name": "assetflow", "backup": backups}]


def test_the_template_has_no_shell_defaults_that_envsubst_would_leave_behind() -> None:
    assert ":-" not in TEMPLATE.read_text(encoding="utf-8")


def test_the_config_is_rendered_with_every_value_filled_in(tmp_path: Path) -> None:
    done = _run(tmp_path, info=_info(), archived="0", BACKUP_S3_ENDPOINT="store.example.test:9000")
    assert done.returncode == 0, done.stderr

    rendered = (tmp_path / "pgbackrest.conf").read_text(encoding="utf-8")
    assert "${" not in rendered
    assert "repo1-s3-endpoint=store.example.test:9000" in rendered
    assert "repo1-s3-key=s3-access-id" in rendered
    assert "repo1-cipher-pass=cipher-value" in rendered
    assert "repo1-s3-bucket=assetflow-backups" in rendered  # a default, applied by the daemon
    if sys.platform != "win32":
        assert stat.S_IMODE((tmp_path / "pgbackrest.conf").stat().st_mode) == 0o600


@pytest.mark.parametrize("missing", ["BACKUP_S3_KEY", "BACKUP_S3_SECRET", "BACKUP_CIPHER_PASS"])
def test_a_missing_credential_refuses_to_render(tmp_path: Path, missing: str) -> None:
    done = _run(tmp_path, info=_info(), archived="0", **{missing: ""})
    assert done.returncode != 0
    assert missing in done.stderr
    assert not (tmp_path / "pgbackrest.conf").exists()


def test_a_value_with_a_line_break_cannot_add_config_lines(tmp_path: Path) -> None:
    done = _run(tmp_path, info=_info(), archived="0", BACKUP_S3_BUCKET="bucket\nrepo1-type=posix")
    assert done.returncode != 0
    assert "line break" in done.stderr


def test_metrics_come_from_pgbackrest_info_and_pg_stat_archiver(tmp_path: Path) -> None:
    now = int(time.time())
    last_backup, last_archive = now - 7200, now - 900
    done = _run(tmp_path, info=_info(now - 90000, last_backup), archived=str(last_archive))
    assert done.returncode == 0, done.stderr

    metrics = _metrics(tmp_path)
    assert metrics["assetflow_backup_last_success_timestamp_seconds"] == last_backup
    assert 900 <= metrics["assetflow_backup_wal_archive_lag_seconds"] < 960
    # The newest restorable point is the later of the last backup and the last archived WAL.
    assert 900 <= metrics["assetflow_backup_restorable_point_age_seconds"] < 960
    assert "assetflow_backup_repo_used_ratio" not in metrics  # no quota set: no invented ratio


def test_no_backup_yet_reports_zero_so_the_stale_backup_alert_fires(tmp_path: Path) -> None:
    done = _run(tmp_path, info=_info(), archived="")
    assert done.returncode == 0, done.stderr
    assert _metrics(tmp_path)["assetflow_backup_last_success_timestamp_seconds"] == 0


def test_repo_used_ratio_is_measured_against_the_quota(tmp_path: Path) -> None:
    now = int(time.time())
    done = _run(
        tmp_path,
        info=_info(now - 100, now - 50, delta=200),
        archived=str(now),
        BACKUP_REPO_QUOTA_BYTES="1000",
    )
    assert done.returncode == 0, done.stderr
    assert _metrics(tmp_path)["assetflow_backup_repo_used_ratio"] == pytest.approx(0.4)
