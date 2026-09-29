#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Dependency license allowlist (master plan §C4.11, §C2.5 fallback without GitHub Advanced Security).

Backend: every package in backend/uv.lock (via `uv export`), licenses read with pip-licenses from the
synced environment. Frontend: every package in frontend/node_modules, licenses read with license-checker
(run `npm ci` first).

Rules:
  - Allowed: MIT, BSD-2-Clause, BSD-3-Clause, Apache-2.0, ISC, PSF-2.0, MPL-2.0, Unicode, CC0-1.0.
    An SPDX `OR` passes when one side is allowed; `AND` needs every side allowed.
  - Copyleft (GPL, AGPL, LGPL) fails for every dependency, runtime or dev. The project itself
    (AGPL-3.0-only) is not a dependency and is skipped.
  - Anything else fails for runtime dependencies unless a maintainer decision is recorded in
    scripts/check-licenses-exceptions.txt (`<ecosystem>:<package> <license> # reason`). For dev-only
    dependencies (not shipped) it is reported as a notice.

Exit code 0 means pass, 1 means a license rule was broken, 2 means the check could not run.

Usage:
    check-licenses.py [--backend-only | --frontend-only]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND = REPO_ROOT / "backend"
FRONTEND = REPO_ROOT / "frontend"
EXCEPTIONS_FILE = REPO_ROOT / "scripts" / "check-licenses-exceptions.txt"

PIP_LICENSES = "pip-licenses==5.5.5"
LICENSE_CHECKER = "license-checker@25.0.1"
PROJECT_PACKAGES = {"python:assetflow", "npm:assetflow-frontend"}

ALLOWED = {
    "MIT",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "Apache-2.0",
    "ISC",
    "PSF-2.0",
    "MPL-2.0",
    "Unicode-3.0",
    "Unicode-DFS-2016",
    "CC0-1.0",
}

# pip-licenses reports trove classifiers or free text; map the common ones to SPDX ids.
ALIASES = {
    "mit": "MIT",
    "mit license": "MIT",
    "the mit license": "MIT",
    "bsd": "BSD-3-Clause",
    "bsd license": "BSD-3-Clause",
    "new bsd license": "BSD-3-Clause",
    "3-clause bsd license": "BSD-3-Clause",
    "bsd 3-clause": "BSD-3-Clause",
    "bsd-3-clause license": "BSD-3-Clause",
    "2-clause bsd license": "BSD-2-Clause",
    "simplified bsd license": "BSD-2-Clause",
    "apache software license": "Apache-2.0",
    "apache 2.0": "Apache-2.0",
    "apache license 2.0": "Apache-2.0",
    "apache license, version 2.0": "Apache-2.0",
    "apache-2.0 license": "Apache-2.0",
    "isc license": "ISC",
    "isc license (iscl)": "ISC",
    "python software foundation license": "PSF-2.0",
    "psf": "PSF-2.0",
    "mozilla public license 2.0 (mpl 2.0)": "MPL-2.0",
    "mpl 2.0": "MPL-2.0",
    "cc0 1.0 universal (cc0 1.0) public domain dedication": "CC0-1.0",
    "unicode-3.0": "Unicode-3.0",
}

COPYLEFT = re.compile(r"(?<![a-z])(a?gpl|lgpl|gnu (affero |lesser |library )?general public)", re.IGNORECASE)


def normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def canonical(term: str) -> str:
    term = term.strip().rstrip("*").strip()
    if term.lower() in ALIASES:
        return ALIASES[term.lower()]
    term = term.strip("()").strip().rstrip("*").strip()
    return ALIASES.get(term.lower(), term)


def split_alternatives(expression: str) -> list[list[str]]:
    """Return the licenses as OR-alternatives of AND-groups. pip-licenses joins classifiers with `;`."""
    alternatives: list[list[str]] = []
    for alt in re.split(r"\s+OR\s+|;", expression):
        group = [canonical(part) for part in re.split(r"\s+AND\s+", alt) if part.strip()]
        if group:
            alternatives.append(group)
    return alternatives


def classify(expression: str) -> str:
    """Return 'allowed', 'copyleft' or 'other'."""
    alternatives = split_alternatives(expression or "UNKNOWN")
    if any(all(lic in ALLOWED for lic in group) for group in alternatives):
        return "allowed"
    if COPYLEFT.search(expression or ""):
        return "copyleft"
    return "other"


def load_exceptions() -> dict[str, str]:
    exceptions: dict[str, str] = {}
    if not EXCEPTIONS_FILE.is_file():
        return exceptions
    for raw in EXCEPTIONS_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        package, _, license_id = line.partition(" ")
        exceptions[package.strip()] = license_id.strip()
    return exceptions


def run(cmd: list[str], cwd: Path) -> str:
    exe = shutil.which(cmd[0])
    if exe is None:
        raise FileNotFoundError(f"{cmd[0]} not found on PATH")
    res = subprocess.run([exe, *cmd[1:]], cwd=str(cwd), capture_output=True, text=True, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed ({res.returncode}):\n{res.stderr.strip()}")
    return res.stdout


def uv_export_names(dev: bool) -> set[str]:
    cmd = ["uv", "export", "--frozen", "--no-emit-project", "--no-hashes", "--format", "requirements-txt"]
    if not dev:
        cmd.append("--no-dev")
    names = set()
    for line in run(cmd, BACKEND).splitlines():
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?==", line.strip())
        if m:
            names.add(normalize_name(m.group(1)))
    return names


def backend_packages() -> list[tuple[str, str, str, bool]]:
    runtime = uv_export_names(dev=False)
    locked = uv_export_names(dev=True)
    out = run(
        ["uv", "run", "--frozen", "--with", PIP_LICENSES, "pip-licenses", "--from=mixed", "--format=json"],
        BACKEND,
    )
    result = []
    for item in json.loads(out):
        name = normalize_name(item["Name"])
        if name not in locked:
            continue  # pip-licenses itself and its helpers
        result.append(
            (f"python:{name}", item.get("Version", ""), item.get("License", "UNKNOWN"), name in runtime)
        )
    return result


def frontend_packages() -> list[tuple[str, str, str, bool]]:
    if not (FRONTEND / "node_modules").is_dir():
        raise FileNotFoundError("frontend/node_modules is missing; run `npm ci` in frontend/ first")
    base = ["npx", "--yes", LICENSE_CHECKER, "--json", "--excludePrivatePackages"]
    everything = json.loads(run(base, FRONTEND))
    production = set(json.loads(run([*base, "--production"], FRONTEND)))
    result = []
    for key, info in everything.items():
        name, _, version = key.rpartition("@")
        licenses = info.get("licenses", "UNKNOWN")
        if isinstance(licenses, list):
            licenses = " OR ".join(licenses)
        result.append((f"npm:{name}", version, licenses, key in production))
    return result


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Dependency license allowlist (§C4.11)")
    side = parser.add_mutually_exclusive_group()
    side.add_argument("--backend-only", action="store_true")
    side.add_argument("--frontend-only", action="store_true")
    args = parser.parse_args(argv)

    packages: list[tuple[str, str, str, bool]] = []
    try:
        if not args.frontend_only:
            packages += backend_packages()
        if not args.backend_only:
            packages += frontend_packages()
    except (FileNotFoundError, RuntimeError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"License check could not run: {exc}\n")
        return 2

    exceptions = load_exceptions()
    failures: list[str] = []
    notices: list[str] = []
    for package, version, license_expr, runtime in sorted(packages):
        if package in PROJECT_PACKAGES:
            continue
        kind = classify(license_expr)
        label = f"{package}@{version} ({'runtime' if runtime else 'dev'}): {license_expr}"
        if kind == "allowed":
            continue
        if kind == "copyleft":
            failures.append(f"{label} is copyleft (§C4.11)")
        elif exceptions.get(package) == license_expr:
            notices.append(f"{label} accepted by maintainer decision (check-licenses-exceptions.txt)")
        elif runtime:
            failures.append(f"{label} is not on the allowlist; record a maintainer decision or replace it")
        else:
            notices.append(f"{label} is not on the allowlist (dev only, not shipped)")

    for n in notices:
        print(f"notice: {n}")
    if failures:
        sys.stderr.write(f"License check failed with {len(failures)} problem(s):\n")
        for f in failures:
            sys.stderr.write(f"  {f}\n")
        return 1
    print(f"License check passed ({len(packages)} package(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
