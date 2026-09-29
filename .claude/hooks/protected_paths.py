#!/usr/bin/env python3
"""PreToolUse Write|Edit|MultiEdit|NotebookEdit: protect branches and sensitive paths.

- never:      .env files (except .env.example), .secrets/, .git/   (no bypass)
- offlimits:  .github/workflows/, ADRs, LICENSE, CLA.md, NOTICE      (bypass ASSETFLOW_OFFLIMITS=ack, logged)
- merged migrations are immutable: a migration file that exists on main may not change
- no edits while on a protected branch (main)
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import state as s  # noqa: E402
from edit_gate import target_path  # noqa: E402


def _exists_on_main(path: str) -> bool:
    r = subprocess.run(["git", "cat-file", "-e", f"main:{path}"], cwd=str(s.repo_root()), capture_output=True)
    return r.returncode == 0


def decide(path: str, current_branch: str) -> tuple[str | None, bool]:
    """Return (reason, bypassable)."""
    cfg = s.config()["protected"]
    if not path:
        return None, False
    if any(re.search(p, path) for p in cfg["never"]):
        return f"{path} is never edited by the agent (secrets live in OpenBao; use .env.example for documentation).", False
    if current_branch in cfg["protected_branches"]:
        return f"you are on {current_branch}. Create a branch first: git checkout -b <type>/<task-id>-<desc>.", False
    if any(re.search(p, path) for p in cfg["offlimits"]):
        return f"{path} is off-limits (workflows, ADRs, license files). The human decides; bypass ASSETFLOW_OFFLIMITS=ack.", True
    if s.is_migration(path) and _exists_on_main(path):
        return f"{path} is already merged; merged migrations never change. Create a new migration (make migration name=...).", False
    return None, False


def main() -> None:
    data = s.hook_input()
    path = target_path(data)
    reason, bypassable = decide(path, s.branch())
    if reason is None:
        s.allow()
    if bypassable and s.flag("ASSETFLOW_OFFLIMITS", "ack"):
        s.log_bypass("ASSETFLOW_OFFLIMITS=ack", f"edit {path}")
        s.allow()
    s.block(reason)


if __name__ == "__main__":
    main()
