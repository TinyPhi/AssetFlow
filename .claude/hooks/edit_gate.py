#!/usr/bin/env python3
"""PreToolUse Write|Edit|MultiEdit|NotebookEdit: no source edit without an approved plan.

Tests and docs may be edited any time (writing the failing test first is encouraged).
Source files must also be inside the plan's scope_paths.
Bypass: ASSETFLOW_GATE=off (logged).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import state as s  # noqa: E402


def target_path(data: dict) -> str:
    tool_input = data.get("tool_input") or {}
    return s.rel_path(tool_input.get("file_path") or tool_input.get("notebook_path") or "")


def decide(path: str, plan: dict | None) -> str | None:
    """Return a block reason, or None to allow."""
    if not path or not s.is_source(path):
        return None
    if not plan:
        return f"{path} is source code and there is no plan. Run /next-task, then the human types approve-plan."
    if not plan.get("approved"):
        return f"plan {plan.get('task_id')} is not approved yet. The human types approve-plan."
    scope = plan.get("scope_paths") or []
    if scope and not any(path.startswith(p) for p in scope):
        return f"{path} is outside the plan's scope_paths {scope}. Stop and write the reason to BLOCKERS.md, or amend the plan (needs a new approve-plan)."
    return None


def main() -> None:
    data = s.hook_input()
    path = target_path(data)
    reason = decide(path, s.read_state("plan"))
    if reason is None:
        s.allow()
    if s.flag("ASSETFLOW_GATE", "off"):
        s.log_bypass("ASSETFLOW_GATE=off", f"edit {path}")
        s.allow()
    s.block(reason)


if __name__ == "__main__":
    main()
