#!/usr/bin/env python3
"""UserPromptSubmit: the only way a plan or a ship gets human approval.

A prompt whose first line starts with `approve-plan` or `approve-ship`
(optionally after "ok", "yes" or "please") records the approval.
Negated or questioning forms ("don't approve-plan", "why approve-ship?") are ignored.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import state as s  # noqa: E402

KEYWORD = re.compile(r"^\s*(?:(?:ok|okay|yes|please)[\s,!.:-]*)?(approve-plan|approve-ship)\b(?!\s*\?)", re.I)


def parse(prompt: str) -> str | None:
    first = (prompt or "").strip().splitlines()[0] if (prompt or "").strip() else ""
    m = KEYWORD.match(first)
    return m.group(1).lower() if m else None


def main() -> None:
    data = s.hook_input()
    keyword = parse(data.get("prompt", ""))
    if keyword is None:
        s.allow()
    if keyword == "approve-plan":
        plan = s.read_state("plan")
        if not plan:
            print("[assetflow-loop] approve-plan: no plan to approve on this branch (run /next-task first).")
            s.allow()
        plan.update(approved=True, approver="human:UserPromptSubmit", approved_iso=s.now_iso())
        s.write_state("plan", plan)
        print(f"[assetflow-loop] plan {plan.get('task_id')} APPROVED by the human. Source edits are now allowed within scope_paths.")
    else:
        current = s.diff_sha()
        s.write_state("ship-approval", {"diff_sha": current, "approver": "human:UserPromptSubmit", "timestamp_iso": s.now_iso()})
        print(f"[assetflow-loop] ship APPROVED by the human for diff {current[:12]}. Any further edit invalidates it.")
    s.allow()


if __name__ == "__main__":
    main()
