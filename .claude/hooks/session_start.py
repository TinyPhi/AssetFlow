#!/usr/bin/env python3
"""SessionStart: print the loop banner, the gate status and the tail of PROGRESS/BLOCKERS."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import gates  # noqa: E402
from lib import state as s  # noqa: E402


def tail(rel: str, n: int = 25) -> str:
    p = s.repo_root() / rel
    if not p.exists():
        return f"({rel} not found)"
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-n:])


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cfg = s.config()
    plan = s.read_state("plan")
    print("AssetFlow delivery loop: PLAN → CODE → DOCS → VERIFY → REVIEW → SECURITY → SHIP")
    print("Human keywords: approve-plan, approve-ship. Helper: python .claude/hooks/af.py status")
    print(f"Branch: {s.branch()}  Plan: {plan['task_id'] + (' (approved)' if plan.get('approved') else ' (waiting for approve-plan)') if plan else 'none (run /next-task)'}")
    if plan:
        open_gates = gates.check_all(for_commit=True)
        if open_gates:
            print("Open gates: " + "; ".join(open_gates[:6]))
    print("\n--- BLOCKERS (tail) ---\n" + tail(cfg["blockers_file"]))
    print("\n--- PROGRESS (tail) ---\n" + tail(cfg["progress_file"]))
    s.allow()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # never break session start
        print(f"[assetflow-loop] session banner unavailable: {exc}")
        sys.exit(0)
