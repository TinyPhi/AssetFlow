#!/usr/bin/env python3
"""PreToolUse Bash: block destructive commands and shell writes that dodge the edit gate.

Quoted strings are stripped first, so `echo "rm -rf /"` is not a match.
Bypass for the Bash-write rule only: ASSETFLOW_GATE=off (logged). Destructive rules have no bypass.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import state as s  # noqa: E402

DESTRUCTIVE = [
    (r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r|-r\s+-f|-f\s+-r)\s+(/|~|\$HOME|\.git\b|\*|\.\.?(\s|$))",
     "rm -rf on a root, home, .git, wildcard or the repo itself"),
    (r"\bfind\b.*\s-delete\b", "find -delete"),
    (r"\b(shred|truncate\s+-s\s*0)\b", "shred / truncate"),
    (r"\bDROP\s+DATABASE\b", "DROP DATABASE"),
    (r"\b(DROP|TRUNCATE)\s+TABLE\b", "DROP/TRUNCATE TABLE outside a migration"),
    (r"\bgit\s+push\b.*(\s--force\b|\s-f\b|--force-with-lease|\s\+\S+)", "force push"),
    (r"\bgit\s+commit\b.*(\s--no-verify\b|\s-n\b)", "git commit --no-verify"),
    (r"\bgit\s+reset\s+--hard\b", "git reset --hard"),
    (r"\bgit\s+clean\s+-[a-zA-Z]*f", "git clean -f"),
    (r"\bgit\s+(checkout|restore)\s+(--\s+)?\.(\s|$)", "discarding all working-tree changes"),
    (r"\bgit\s+add\s+(-A|--all|\.)(\s|$)", "git add -A / git add . (stage explicit paths)"),
    (r"\bgit\s+merge(\s|$)|\bgh\s+pr\s+merge\b", "merging (the agent never merges)"),
]

# Shell writes into files: redirects, tee, sed -i, cp/mv onto a path.
WRITE_TARGETS = [
    r"(?:^|[^<>0-9&])>>?\s*([^\s;&|<>]+)",
    r"\btee\s+(?:-a\s+)?([^\s;&|]+)",
    r"\bsed\s+-i[^\s]*\s+.*?\s([^\s;&|]+)\s*$",
    r"\b(?:cp|mv)\s+(?:-\S+\s+)*\S+\s+([^\s;&|]+)",
]


def destructive_reason(command: str) -> str | None:
    bare = s.strip_quotes(command)
    for pattern, label in DESTRUCTIVE:
        if re.search(pattern, bare, flags=re.I if "TABLE" in pattern or "DATABASE" in pattern else 0):
            if "TABLE" in pattern and re.search(r"migrations?/", command):
                continue
            return label
    return None


def shell_write_targets(command: str) -> list[str]:
    bare = s.strip_quotes(command)
    targets: list[str] = []
    for pattern in WRITE_TARGETS:
        for m in re.finditer(pattern, bare, flags=re.M):
            t = m.group(1)
            if t and t not in ("/dev/null", "&1", "&2"):
                targets.append(s.rel_path(t))
    return targets


def main() -> None:
    data = s.hook_input()
    command = (data.get("tool_input") or {}).get("command", "")
    if not command:
        s.allow()
    reason = destructive_reason(command)
    if reason:
        s.block(f"{reason} is not allowed. Ask the human to run it if it is really needed.")
    forged = [t for t in shell_write_targets(command) if t.startswith(".claude/state/")]
    if forged or re.search(r"\.claude/state/", s.strip_quotes(command)) and re.search(r"\b(rm|mv|cp|sed|tee)\b", command):
        s.block("gate state in .claude/state is written only by af.py and the hooks.")
    plan = s.read_state("plan")
    guarded =[t for t in shell_write_targets(command) if s.is_source(t)]
    if guarded and not (plan and plan.get("approved")):
        if s.flag("ASSETFLOW_GATE", "off"):
            s.log_bypass("ASSETFLOW_GATE=off", f"bash write {guarded}")
            s.allow()
        s.block(f"shell write to source {guarded} without an approved plan. Use the Edit tool after approve-plan.")
    s.allow()


if __name__ == "__main__":
    main()
