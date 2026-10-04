# SPDX-FileCopyrightText: 2026 TinyPhi <conduct@tinyphi.com>
# SPDX-License-Identifier: AGPL-3.0-only

import sys
from importlib import import_module
from pathlib import Path

scripts_dir = Path(__file__).parent.parent
sys.path.insert(0, str(scripts_dir))

hardening_mod = import_module("check-container-hardening")
evaluate_container = hardening_mod.evaluate_container


def test_hardened_container_passes():
    valid = {
        "Name": "/af-api",
        "Config": {
            "User": "10001:10001",
            "Healthcheck": {"Test": ["CMD", "curl", "-f", "http://localhost:8080/healthz"]},
        },
        "HostConfig": {
            "ReadonlyRootfs": True,
            "SecurityOpt": ["no-new-privileges:true"],
            "CapDrop": ["ALL"],
            "Memory": 536870912,
        },
    }
    violations = evaluate_container(valid)
    assert violations == []


def test_unhardened_container_fails():
    invalid = {
        "Name": "/af-custom",
        "Config": {
            "User": "0",
            "Healthcheck": {},
        },
        "HostConfig": {
            "ReadonlyRootfs": False,
            "SecurityOpt": [],
            "CapDrop": [],
            "Memory": 0,
        },
    }
    violations = evaluate_container(invalid)
    assert len(violations) >= 5
    assert any("root" in v for v in violations)
    assert any("read-only" in v for v in violations)
    assert any("no-new-privileges" in v for v in violations)
    assert any("CapDrop" in v for v in violations)
    assert any("memory" in v for v in violations)


def test_documented_exceptions_handled():
    postgres = {
        "Name": "/af-postgres",
        "Config": {
            "User": "999:999",
            "Healthcheck": {"Test": ["CMD-SHELL", "pg_isready"]},
        },
        "HostConfig": {
            "ReadonlyRootfs": False,  # allowed by exception
            "SecurityOpt": ["no-new-privileges:true"],
            "CapDrop": ["ALL"],
            "Memory": 1073741824,
        },
    }
    violations = evaluate_container(postgres)
    assert violations == []
