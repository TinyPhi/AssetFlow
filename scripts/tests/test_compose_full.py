# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""`docker compose config` checks of deploy/compose.full.yml (AF-017).

Only renders the configuration: no container, network or volume is created. Skipped when the
Docker CLI with the compose plugin is not installed.

Run: make test-scripts
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

COMPOSE_FILE = Path(__file__).resolve().parent.parent.parent / "deploy" / "compose.full.yml"
OVERRIDES = ("ZITADEL_EXTERNALSECURE", "ZITADEL_TLS_MODE", "API_HOST_PORT", "ZITADEL_EXTERNALPORT")


def _render(monkeypatch: pytest.MonkeyPatch, **env: str) -> dict[str, Any]:
    if shutil.which("docker") is None:
        pytest.skip("docker CLI not installed")
    for name in OVERRIDES:
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    done = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "config", "--format", "json"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if done.returncode != 0 and "is not a docker command" in done.stderr:
        pytest.skip("docker compose plugin not installed")
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_every_published_port_binds_to_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    services = _render(monkeypatch)["services"]
    for name in ("api", "zitadel"):
        assert services[name]["ports"], f"{name} publishes no port"
    for name, service in services.items():
        for port in service.get("ports", []):
            assert port.get("host_ip") == "127.0.0.1", f"{name} publishes {port} on every interface"


def test_zitadel_external_secure_defaults_to_true(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _render(monkeypatch)
    assert config["services"]["zitadel"]["environment"]["ZITADEL_EXTERNALSECURE"] == "true"
    assert "external" in config["services"]["zitadel"]["command"]


def test_external_secure_can_still_be_switched_off_for_local_http(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _render(monkeypatch, ZITADEL_EXTERNALSECURE="false", ZITADEL_TLS_MODE="disabled")
    assert config["services"]["zitadel"]["environment"]["ZITADEL_EXTERNALSECURE"] == "false"
