#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Port and name preflight for `make up-full`, `make up-identity` and `make dev`.

Each profile publishes a few host ports; every one must be above 9000 (other projects on the same
machine use the usual low ports) and free. A port that is already taken stops the start with a
message that names the port and the variable that moves it. A port held by a container of this
project (label `com.tinyphi.project=assetflow`) is fine: that is the stack being started again.

Every service of a profile has a fixed container name (`af-<service>`). A container that already
owns one of those names but is not part of this stack (no label `com.tinyphi.project=assetflow`, or
another compose project) stops the start too: it is named, and never touched.
Nothing outside the `assetflow` project is ever changed; this script only reads.

Usage:
    python scripts/check-ports.py full|identity|minimal|dev [--env-file .env.local]

Standard library only.
"""

from __future__ import annotations

import argparse
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

#: profile -> {environment variable: default host port}
PROFILES: dict[str, dict[str, int]] = {
    "full": {
        "OPENBAO_HOST_PORT": 19200,
        "POSTGRES_HOST_PORT": 15432,
        "ZITADEL_EXTERNALPORT": 19081,
        "API_HOST_PORT": 18080,
    },
    "minimal": {
        "DATABASE_PORT": 15432,
        "WEB_PORT": 18080,
        "MAILPIT_SMTP_PORT": 11025,
        "MAILPIT_WEB_PORT": 18025,
    },
    "identity": {"ZITADEL_EXTERNALPORT": 19081},
    "dev": {
        "OPENBAO_HOST_PORT": 19200,
        "POSTGRES_HOST_PORT": 15432,
        "ZITADEL_EXTERNALPORT": 19081,
        "API_HOST_PORT": 18090,
        "WEB_PORT": 18080,
    },
}
#: ports of the optional dev containers, checked only when the profile is switched on (MAIL=1, ...)
DEV_OPTIONAL: dict[str, dict[str, int]] = {
    "MAIL": {"MAILPIT_SMTP_PORT": 11025, "MAILPIT_WEB_PORT": 18025},
    "OBSERVABILITY": {"GRAFANA_HOST_PORT": 13000, "OTLP_GRPC_HOST_PORT": 14317},
}
#: profile -> compose file that names its containers (`container_name:`) and its project (`name:`)
COMPOSE_FILES: dict[str, str] = {
    "full": "compose.full.yml",
    "identity": "compose.identity.yml",
    "minimal": "compose.minimal.yml",
    "dev": "compose.dev.yml",
}
PROJECT_LABEL = "com.tinyphi.project=assetflow"
MIN_PORT = 9001
HOST = "127.0.0.1"


def read_env_file(path: Path) -> dict[str, str]:
    """`KEY=VALUE` lines of a compose env file (comments and blank lines ignored)."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
        if match:
            values[match.group(1)] = match.group(2).strip().strip('"').strip("'")
    return values


def chosen_ports(profile: str, env: dict[str, str]) -> dict[str, int]:
    """The host port each variable resolves to (environment first, then the default)."""
    ports: dict[str, int] = {}
    wanted = dict(PROFILES[profile])
    if profile == "dev":
        for switch, extra in DEV_OPTIONAL.items():
            if env.get(switch) == "1":
                wanted.update(extra)
    for name, default in wanted.items():
        raw = env.get(name)
        if raw in (None, ""):
            ports[name] = default
            continue
        try:
            ports[name] = int(str(raw))
        except ValueError as exc:
            raise ValueError(f"{name}={raw!r} is not a port number") from exc
    return ports


def is_free(port: int) -> bool:
    """True when nothing is listening on `port` of the loopback address."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((HOST, port)) != 0


def assetflow_ports() -> set[int]:
    """Host ports published by running containers of this project; empty when docker is not usable."""
    try:
        out = subprocess.run(
            ["docker", "ps", "--filter", "label=com.tinyphi.project=assetflow", "--format", "{{.Ports}}"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    return {int(m) for m in re.findall(r":(\d+)->", out)}


def compose_names(profile: str) -> tuple[str, list[str]]:
    """The compose project name and the fixed container names of a profile's compose file."""
    text = (Path(__file__).resolve().parent.parent / "deploy" / COMPOSE_FILES[profile]).read_text(
        encoding="utf-8"
    )
    project = re.search(r"^name:\s*(\S+)", text, re.MULTILINE)
    names = re.findall(r"^\s+container_name:\s*(\S+)", text, re.MULTILINE)
    return (project.group(1) if project else ""), names


def existing_containers() -> dict[str, tuple[str, str, str]]:
    """name -> (label com.tinyphi.project, compose project, compose files) of every container."""
    fmt = (
        '{{.Names}}|{{.Label "com.tinyphi.project"}}|{{.Label "com.docker.compose.project"}}'
        '|{{.Label "com.docker.compose.project.config_files"}}'
    )
    try:
        out = subprocess.run(
            ["docker", "ps", "-a", "--format", fmt],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    found: dict[str, tuple[str, str, str]] = {}
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) == 4:
            found[parts[0]] = (parts[1], parts[2], parts[3])
    return found


def name_problems(profile: str, existing: dict[str, tuple[str, str, str]] | None = None) -> list[str]:
    """One message per af- container name that is taken by a container that is not this stack."""
    project, names = compose_names(profile)
    present = existing_containers() if existing is None else existing
    found: list[str] = []
    for name in names:
        if name not in present:
            continue
        label, compose_project, files = present[name]
        if label != "assetflow":
            found.append(
                f"container name {name} is owned by a container that does not belong to AssetFlow "
                f"(no label {PROJECT_LABEL}). It is left alone; stop using that name there or remove it yourself."
            )
        elif (
            compose_project != project
            or Path(files.split(",")[0].strip().replace("\\", "/")).name != COMPOSE_FILES[profile]
        ):
            found.append(
                f"container name {name} is held by another AssetFlow stack (compose project "
                f"{compose_project or 'none'}, file {files or 'none'}; this stack is {project}, "
                f"{COMPOSE_FILES[profile]}). Starting would replace it, so nothing is started; remove it "
                f"yourself (docker rm {name}) if it is a leftover."
            )
    return found


def problems(profile: str, env: dict[str, str]) -> list[str]:
    """One message per port or container name that cannot be used."""
    found: list[str] = []
    try:
        ports = chosen_ports(profile, env)
    except ValueError as exc:
        return [str(exc)]
    ours = assetflow_ports()
    for name, port in sorted(ports.items()):
        if not MIN_PORT <= port <= 65535:
            found.append(f"{name}={port}: AssetFlow host ports must be above 9000 (and at most 65535).")
        elif not is_free(port) and port not in ours:
            found.append(
                f"{name}={port}: port {port} is already in use. Set {name} to a free port above 9000."
            )
    clashes = {p for p in ports.values() if list(ports.values()).count(p) > 1}
    found.extend(f"port {p} is chosen twice; give each service its own." for p in sorted(clashes))
    found.extend(name_problems(profile))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("profile", choices=sorted(PROFILES))
    parser.add_argument("--env-file", type=Path, default=Path(".env.local"))
    args = parser.parse_args(argv)
    env = {**read_env_file(args.env_file), **os.environ}
    found = problems(args.profile, env)
    for message in found:
        sys.stderr.write(f"check-ports: {message}\n")
    if found:
        sys.stderr.write("check-ports: nothing was started and no container was touched.\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
