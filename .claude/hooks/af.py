#!/usr/bin/env python3
"""af.py — the AssetFlow delivery-loop helper.

Usage (run from anywhere inside the repo):
  af.py next-task                      print the next tracker task as a draft plan (JSON)
  af.py plan set < plan.json           freeze a plan (approved=false until the human types approve-plan)
  af.py plan show | af.py plan check <AC-id>
  af.py verify                         run loop.json verify_commands, record exit codes for this diff
  af.py review set < review.json       record the review (checks tests rules)
  af.py security set < security.json   record the security-reviewer verdict
  af.py docs --touched | --skip "<reason>"
  af.py ship                           after explicit `git add <paths>`: record the staged tree (TTL)
  af.py done                           claim the unit done (the Stop hook then checks nothing is left uncommitted)
  af.py status                         show every gate for the current branch

Plan approval is HUMAN-ONLY: there is no `plan approve` command.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import gates  # noqa: E402
from lib import state as s  # noqa: E402

STATUS_MARKS = "☐◐☑⛔"


def _stdin_json() -> dict:
    raw = sys.stdin.read()
    if raw.strip() in ("", "-"):
        sys.exit("expected a JSON object on stdin")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        sys.exit(f"invalid JSON on stdin: {exc}")
    if not isinstance(data, dict):
        sys.exit("expected a JSON object")
    return data


def _fail(msg: str) -> None:
    sys.stderr.write(f"af.py: {msg}\n")
    sys.exit(1)


# ------------------------------------------------------------------ next-task


def parse_tracker(text: str) -> list[dict]:
    """Rows like `| M1.1-T3 | Task text | Done when | ☐ |` (status is the last marked cell).

    Extra columns (owner, depends on) are tolerated: the first text cell is the title,
    the last text cell before the status is "Done when".
    """
    tasks = []
    for line in text.splitlines():
        m = re.match(r"^\|\s*(M\d+\.\d+-T\d+)\s*\|(.*)\|\s*$", line)
        if not m:
            continue
        cells = [c.strip() for c in m.group(2).split("|")]
        status = next((c for c in reversed(cells) if c and c[0] in STATUS_MARKS), "☐")
        text_cells = [c for c in cells if c and c[0] not in STATUS_MARKS]
        tasks.append(
            {
                "task_id": m.group(1),
                "milestone": m.group(1).split("-")[0],
                "title": text_cells[0] if text_cells else "",
                "done_when": text_cells[-1] if len(text_cells) > 1 else "",
                "status": status[0],
            }
        )
    return tasks


def pick_next(tasks: list[dict]) -> dict | None:
    for t in tasks:  # resume work in progress first
        if t["status"] == "◐":
            return t
    for t in tasks:
        if t["status"] != "☐":
            continue
        same_milestone = [x for x in tasks if x["milestone"] == t["milestone"]]
        earlier = same_milestone[: same_milestone.index(t)]
        if all(x["status"] == "☑" for x in earlier):
            return t
    return None


def cmd_next_task() -> None:
    tracker = s.repo_root() / s.config()["tracker"]
    if not tracker.exists():
        _fail(f"tracker not found: {s.config()['tracker']} (created in M1.1; until then give the task explicitly)")
    task = pick_next(parse_tracker(tracker.read_text(encoding="utf-8")))
    if task is None:
        print(json.dumps({"result": "no task ready: every task is done, blocked, or waiting on an earlier task"}))
        return
    draft = {
        "task_id": task["task_id"],
        "title": task["title"],
        "commit_type": "feat",
        "spec_ref": "",
        "adr_refs": [],
        "acceptance_criteria": [
            {"id": "AC1", "text": task["done_when"] or task["title"], "verify": "make verify", "done": False}
        ],
        "scope_paths": [],
        "tests_waiver": "",
        "isolation_waiver": "",
    }
    print(json.dumps(draft, indent=2, ensure_ascii=False))


# ------------------------------------------------------------------ plan


def cmd_plan(args: list[str]) -> None:
    sub = args[0] if args else "show"
    if sub == "set":
        data = _stdin_json()
        for key in ("task_id", "title", "commit_type", "acceptance_criteria", "scope_paths"):
            if key not in data:
                _fail(f"plan needs {key!r}")
        if data["commit_type"] not in s.config()["commit_types"]:
            _fail(f"commit_type must be one of {s.config()['commit_types']}")
        if not data["acceptance_criteria"] or not all(
            isinstance(ac, dict) and ac.get("id") and ac.get("text") and ac.get("verify")
            for ac in data["acceptance_criteria"]
        ):
            _fail("each acceptance criterion needs id, text and verify")
        if not data["scope_paths"]:
            _fail("scope_paths must list the paths this task may touch")
        existing = s.read_state("plan")
        if existing and existing.get("approved") and existing.get("task_id") == data["task_id"]:
            _fail("an approved plan for this task exists; changing it needs a new approve-plan (delete it first)")
        approved = s.flag("ASSETFLOW_PLAN_AUTOPASS")
        if approved:
            s.log_bypass("ASSETFLOW_PLAN_AUTOPASS", data["task_id"])
        data.update(
            branch=s.branch(),
            base_sha=s.head_sha(),
            created_iso=s.now_iso(),
            approved=approved,
            approver="autopass" if approved else None,
        )
        s.write_state("plan", data)
        print(f"plan frozen for {data['task_id']}; approved={approved}. The human types: approve-plan")
    elif sub == "show":
        print(json.dumps(s.read_state("plan"), indent=2, ensure_ascii=False))
    elif sub == "check":
        if len(args) < 2:
            _fail("usage: af.py plan check <AC-id>")
        plan = s.read_state("plan") or _fail("no plan")
        for ac in plan["acceptance_criteria"]:
            if ac["id"] == args[1]:
                ac["done"] = True
                s.write_state("plan", plan)
                print(f"{args[1]} marked done")
                return
        _fail(f"no criterion {args[1]}")
    elif sub == "approve":
        _fail("plan approval is HUMAN-ONLY: the human types approve-plan in the chat")
    else:
        _fail(f"unknown plan subcommand {sub!r}")


# ------------------------------------------------------------------ verify


def cmd_verify() -> None:
    results: dict[str, int] = {}
    for command in s.config()["verify_commands"]:
        print(f"$ {command}", flush=True)
        proc = subprocess.run(command, shell=True, cwd=str(s.repo_root()))
        results[command] = proc.returncode
        if proc.returncode != 0:
            print(f"  -> exit {proc.returncode}", flush=True)
    passed = all(code == 0 for code in results.values())
    s.write_state(
        "verify",
        {"diff_sha": s.diff_sha(), "results": results, "passed": passed, "timestamp_iso": s.now_iso()},
    )
    print("LOOP_VERIFY_PASS" if passed else "LOOP_VERIFY_FAIL")
    sys.exit(0 if passed else 1)


# ------------------------------------------------------------------ review / security / docs


def cmd_review(args: list[str]) -> None:
    if args[:1] != ["set"]:
        _fail("usage: af.py review set < review.json")
    plan = s.read_state("plan")
    if not plan or not plan.get("approved"):
        _fail("review needs an APPROVED plan")
    files = s.changed_files()
    if not files:
        _fail("nothing changed against HEAD")
    data = _stdin_json()
    if data.get("verdict") not in ("approve", "changes"):
        _fail("verdict must be 'approve' or 'changes'")
    if not isinstance(data.get("dod_met"), bool):
        _fail("dod_met must be true or false")
    out_of_scope = [
        f for f in files if plan["scope_paths"] and not any(f.startswith(p) for p in plan["scope_paths"])
    ]
    problems = gates.tests_problems(files, plan, data.get("repro_test"))
    if out_of_scope:
        problems.append("files outside scope_paths: " + ", ".join(out_of_scope[:8]))
    data.update(diff_sha=s.diff_sha(), reviewed_iso=s.now_iso(), tests_problems=problems)
    s.write_state("review", data)
    if problems:
        print("review recorded WITH problems (the commit gate will refuse):\n  - " + "\n  - ".join(problems))
        sys.exit(1)
    print("review recorded")


def cmd_security(args: list[str]) -> None:
    if args[:1] != ["set"]:
        _fail("usage: af.py security set < security.json")
    data = _stdin_json()
    if data.get("verdict") not in ("pass", "notes", "block"):
        _fail("verdict must be pass, notes or block")
    data.update(diff_sha=s.diff_sha(), reviewed_iso=s.now_iso(), reviewer=data.get("reviewer", "security-reviewer"))
    s.write_state("security", data)
    print(f"security verdict recorded: {data['verdict']}")


def cmd_docs(args: list[str]) -> None:
    files = s.changed_files()
    if args[:1] == ["--touched"]:
        docs = [f for f in files if s.is_doc(f)]
        if not docs:
            _fail("--touched but no doc file changed (docs/, README, CLAUDE.md, CHANGELOG ...)")
        record = {"mode": "touched", "touched_docs": docs}
    elif args[:1] == ["--skip"] and len(args) > 1 and args[1].strip():
        plan = s.read_state("plan") or {}
        allowed = s.config()["docs_skip_allowed_types"]
        if plan.get("commit_type") not in allowed:
            _fail(f"docs may be skipped only for commit types {allowed}; this is {plan.get('commit_type')!r}")
        record = {"mode": "skip", "skip_reason": args[1].strip()}
    else:
        _fail('usage: af.py docs --touched | --skip "<reason>"')
    record.update(diff_sha=s.diff_sha(), timestamp_iso=s.now_iso())
    s.write_state("docs", record)
    print(f"docs recorded ({record['mode']})")


# ------------------------------------------------------------------ ship / done / status


def cmd_ship() -> None:
    if not s.staged_files():
        _fail("nothing staged: git add the exact paths first (never git add -A)")
    if s.unstaged_files():
        _fail("unstaged changes present: stage or discard them first")
    stray = [f for f in s.untracked_files() if s.is_source(f) or s.is_test(f)]
    if stray:
        _fail("untracked source/test files not staged: " + ", ".join(stray[:8]))
    problems = gates.check_all(for_commit=False)
    if problems:
        _fail("gates not met:\n  - " + "\n  - ".join(problems))
    s.write_state(
        "ship-ready",
        {"staged_tree_sha": s.staged_tree_sha(), "head": s.head_sha(), "diff_sha": s.diff_sha(), "timestamp_iso": s.now_iso()},
    )
    print(f"ship-ready recorded (valid {s.config()['ship_ttl_minutes']} min). Commit with a Conventional Commit message.")


def cmd_done() -> None:
    s.write_state("claimed-done", {"timestamp_iso": s.now_iso(), "head": s.head_sha()})
    print("claimed done; the Stop hook will refuse to end the session while source changes are uncommitted")


def cmd_status() -> None:
    plan = s.read_state("plan")
    print(f"branch: {s.branch()}")
    print(f"plan:   {plan['task_id'] + (' (approved)' if plan.get('approved') else ' (NOT approved)') if plan else '-'}")
    problems = gates.check_all(for_commit=True)
    if problems:
        print("open gates:")
        for p in problems:
            print(f"  - {p}")
    else:
        print("all gates met: git commit may proceed")


def main(argv: list[str]) -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return
    cmd, rest = argv[0], argv[1:]
    handlers = {
        "next-task": lambda: cmd_next_task(),
        "plan": lambda: cmd_plan(rest),
        "verify": lambda: cmd_verify(),
        "review": lambda: cmd_review(rest),
        "security": lambda: cmd_security(rest),
        "docs": lambda: cmd_docs(rest),
        "ship": lambda: cmd_ship(),
        "done": lambda: cmd_done(),
        "status": lambda: cmd_status(),
    }
    if cmd not in handlers:
        _fail(f"unknown command {cmd!r}; see af.py --help")
    handlers[cmd]()


if __name__ == "__main__":
    main(sys.argv[1:])
