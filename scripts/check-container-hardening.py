#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 TinyPhi <conduct@tinyphi.com>
# SPDX-License-Identifier: AGPL-3.0-only
"""Validates that running AssetFlow containers satisfy container hardening rules (§C5.10, §B11.1)."""

import json
import subprocess
import sys
from typing import Any

# Documented exceptions for third-party images that require specific privileges or read-write filesystem.
EXCEPTIONS: dict[str, dict[str, str]] = {
    "af-postgres": {
        "readonly_rootfs": "PostgreSQL image requires write access to internal configuration and run directories",
    },
    "af-zitadel": {
        "readonly_rootfs": "Zitadel binary creates temporary runtime assets",
    },
    "af-mailpit": {
        "readonly_rootfs": "Mailpit stores ephemeral messages in internal database",
        "user": "Mailpit container runs as its default unprivileged service user",
    },
    "af-openbao": {
        "cap_drop": "OpenBao requires IPC_LOCK capability for memory protection",
    },
}


def evaluate_container(data: dict[str, Any]) -> list[str]:
    name = data.get("Name", "").lstrip("/")
    config = data.get("Config", {})
    host_config = data.get("HostConfig", {})
    exceptions = EXCEPTIONS.get(name, {})

    violations: list[str] = []

    # 1. Non-root user
    user = str(config.get("User", "")).strip()
    if (not user or user == "0" or user == "root") and "user" not in exceptions:
        violations.append(f"{name}: runs as root or unspecified user ({user or 'empty'})")

    # 2. Read-only root filesystem
    readonly = host_config.get("ReadonlyRootfs", False)
    if not readonly and "readonly_rootfs" not in exceptions:
        violations.append(f"{name}: root filesystem is not read-only")

    # 3. No new privileges
    sec_opts = host_config.get("SecurityOpt") or []
    if not any("no-new-privileges" in str(opt).lower() for opt in sec_opts) and "no_new_privileges" not in exceptions:
        violations.append(f"{name}: missing no-new-privileges security option")

    # 4. Cap drop ALL
    cap_drop = host_config.get("CapDrop") or []
    if "ALL" not in cap_drop and "all" not in cap_drop and "cap_drop" not in exceptions:
        violations.append(f"{name}: does not drop ALL capabilities (CapDrop: {cap_drop})")

    # 5. Memory limit
    memory = host_config.get("Memory", 0)
    if memory <= 0 and "memory" not in exceptions:
        violations.append(f"{name}: memory limit is not set")

    # 6. Healthcheck defined
    healthcheck = config.get("Healthcheck", {})
    if (not healthcheck or not healthcheck.get("Test")) and "healthcheck" not in exceptions:
        violations.append(f"{name}: healthcheck is not defined")

    return violations


def check_containers(raw_json: str | None = None) -> int:
    if raw_json is not None:
        try:
            inspect_data = json.loads(raw_json)
        except (ValueError, TypeError) as err:
            print(f"Failed to parse inspect JSON: {err}", file=sys.stderr)
            return 1
    else:
        try:
            cmd = ["docker", "ps", "--filter", "label=com.tinyphi.project=assetflow", "-q"]
            ps_proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
            container_ids = [c.strip() for c in ps_proc.stdout.splitlines() if c.strip()]
            if not container_ids:
                print("No running AssetFlow containers found.")
                return 0

            inspect_cmd = ["docker", "inspect"] + container_ids
            insp_proc = subprocess.run(inspect_cmd, capture_output=True, text=True, check=True)
            inspect_data = json.loads(insp_proc.stdout)
        except (subprocess.SubprocessError, ValueError, OSError) as err:
            print(f"Error inspecting containers: {err}", file=sys.stderr)
            return 1

    all_violations: list[str] = []
    for c in inspect_data:
        all_violations.extend(evaluate_container(c))

    if all_violations:
        print("Container hardening violations found:")
        for v in all_violations:
            print(f"  - {v}")
        return 1

    print("All inspected AssetFlow containers comply with container hardening standards.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--input-json":
        with open(sys.argv[2], "r", encoding="utf-8") as f:
            sys.exit(check_containers(f.read()))
    sys.exit(check_containers())
