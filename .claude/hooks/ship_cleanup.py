#!/usr/bin/env python3
"""PostToolUse Bash: after a successful commit, clear the one-shot gate artifacts.

The plan stays (a task can take several commits); verify, review, security, docs,
ship-approval, ship-ready and claimed-done are cleared once HEAD has moved past
the ship-ready marker.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import state as s  # noqa: E402
from commit_gate import is_commit  # noqa: E402


def main() -> None:
    data = s.hook_input()
    command = (data.get("tool_input") or {}).get("command", "")
    if not command or not is_commit(command):
        s.allow()
    ready = s.read_state("ship-ready")
    if ready and ready.get("head") != s.head_sha():
        for kind in s.ONE_SHOT_KINDS:
            s.delete_state(kind)
        print("[assetflow-loop] commit landed; one-shot gate artifacts cleared. Next: push, open the PR, watch CI. Never merge.")
    s.allow()


if __name__ == "__main__":
    main()
