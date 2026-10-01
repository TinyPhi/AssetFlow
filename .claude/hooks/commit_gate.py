#!/usr/bin/env python3
"""PreToolUse Bash: `git commit` passes only when every gate is met for the exact staged diff.

Checks (lib/gates.check_all): approved plan, verify passed, review approve + DoD + tests rules,
security-reviewer verdict for security paths, migration ↔ isolation test, docs, human approve-ship,
fresh ship-ready marker matching the staged tree, no unstaged changes.
Also checks the Conventional Commit subject when it is given with -m.
Bypass: ASSETFLOW_GATE=off (logged).
"""

from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import gates  # noqa: E402
from lib import state as s  # noqa: E402

COMMIT = re.compile(r"(?:^|[;&|(]\s*|\s)git\s+(?:-C\s+\S+\s+)?commit\b")


def is_commit(command: str) -> bool:
    return bool(COMMIT.search(s.strip_quotes(command)))


def commit_subject(command: str) -> str | None:
    try:
        parts = shlex.split(command, posix=True)
    except ValueError:
        return None
    for i, part in enumerate(parts):
        if part in ("-m", "--message") and i + 1 < len(parts):
            return parts[i + 1].splitlines()[0]
        if part.startswith("--message="):
            return part.split("=", 1)[1].splitlines()[0]
    return None


def subject_problems(subject: str) -> list[str]:
    cfg = s.config()
    types = "|".join(cfg["commit_types"])
    m = re.match(rf"^({types})(\(([a-z0-9-]+)\))?(!)?: \S.*$", subject)
    if not m:
        return [f"commit subject {subject!r} is not a Conventional Commit: <type>(<scope>): <subject>"]
    problems = []
    if m.group(3) in cfg["forbidden_commit_scopes"]:
        problems.append(f"scope {m.group(3)!r} is not allowed")
    if len(subject) > 72:
        problems.append("commit subject is longer than 72 characters")
    if subject.split(": ", 1)[1][:1].isupper():
        problems.append("commit subject must start lowercase")
    if "Signed-off-by" in subject:
        problems.append("no Signed-off-by: AssetFlow uses a CLA, not DCO")
    return problems


def main() -> None:
    data = s.hook_input()
    command = (data.get("tool_input") or {}).get("command", "")
    if not command or not is_commit(command):
        s.allow()
    problems = gates.check_all(for_commit=True)
    subject = commit_subject(command)
    if subject:
        problems += subject_problems(subject)
    if not problems:
        s.allow()
    if s.flag("ASSETFLOW_GATE", "off"):
        s.log_bypass("ASSETFLOW_GATE=off", "commit with open gates: " + "; ".join(problems))
        s.allow()
    s.block("git commit refused. Open gates:\n  - " + "\n  - ".join(problems) + "\nRun: python .claude/hooks/af.py status")


if __name__ == "__main__":
    main()
