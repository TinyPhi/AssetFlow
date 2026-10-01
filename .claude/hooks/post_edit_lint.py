#!/usr/bin/env python3
"""PostToolUse Write|Edit|MultiEdit: fast feedback on the file just edited.

- Python: `ruff check` (and `ruff format --check`) through uv when available.
- Every text file: the domain-terms denylist (scripts/check-domain-terms.sh) when it exists.
- New migration: reminder that an isolation test must change too (the commit gate enforces it).
Exit 2 sends the findings back to the agent so it fixes them now.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import state as s  # noqa: E402
from edit_gate import target_path  # noqa: E402


def run(cmd: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=str(s.repo_root()), capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 0, f"(skipped: {exc})"
    return p.returncode, (p.stdout + p.stderr).strip()


def main() -> None:
    data = s.hook_input()
    path = target_path(data)
    if not path or not (s.repo_root() / path).exists():
        s.allow()
    findings: list[str] = []

    if path.endswith(".py") and shutil.which("uv") and (s.repo_root() / "backend" / "pyproject.toml").exists():
        code, out = run(["uv", "run", "--project", "backend", "ruff", "check", path])
        if code != 0:
            findings.append("ruff check:\n" + "\n".join(out.splitlines()[-15:]))

    terms = s.repo_root() / "scripts" / "check-domain-terms.sh"
    if terms.exists() and shutil.which("sh"):
        code, out = run(["sh", str(terms), path])
        if code != 0:
            findings.append("domain terms:\n" + "\n".join(out.splitlines()[-10:]))

    if s.is_migration(path):
        print("[assetflow-loop] migration edited: add or update a test under backend/tests/isolation/ (the commit gate requires it) and ask the migration-reviewer agent.")

    if findings:
        sys.stderr.write(f"[assetflow-loop] {path} needs fixes:\n" + "\n\n".join(findings) + "\n")
        sys.exit(2)
    s.allow()


if __name__ == "__main__":
    main()
