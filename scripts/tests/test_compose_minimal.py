# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""`docker compose config` checks of deploy/compose.minimal.yml.

Every service built from the backend image loads config/assetflow.yaml, which has no defaults for
ASSETFLOW_ENV and ASSETFLOW_AUTH_PROVIDER, so `make up-minimal` needs both set by the compose file.
Only renders the configuration; skipped when the Docker CLI with the compose plugin is missing.

Run: make test-scripts
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

COMPOSE_FILE = Path(__file__).resolve().parent.parent.parent / "deploy" / "compose.minimal.yml"
REQUIRED = ("ASSETFLOW_ENV", "ASSETFLOW_AUTH_PROVIDER")


def _render(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    if shutil.which("docker") is None:
        pytest.skip("docker CLI not installed")
    for name in REQUIRED:
        monkeypatch.delenv(name, raising=False)
    done = subprocess.run(
        ["docker", "compose", "--profile", "tools", "-f", str(COMPOSE_FILE), "config", "--format", "json"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if done.returncode != 0 and "is not a docker command" in done.stderr:
        pytest.skip("docker compose plugin not installed")
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_every_backend_service_sets_env_and_auth_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    services = _render(monkeypatch)["services"]
    backend = {
        name: svc
        for name, svc in services.items()
        if Path(svc.get("build", {}).get("context", "")).name == "backend"
    }
    assert {"api", "worker", "migrate"} <= set(backend)
    for name, svc in backend.items():
        env = svc["environment"]
        assert env.get("ASSETFLOW_ENV") == "development", name
        assert env.get("ASSETFLOW_AUTH_PROVIDER") == "mock", name
