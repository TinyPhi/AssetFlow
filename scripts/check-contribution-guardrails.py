#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Contribution guardrails for pull requests (master plan §C9.4).

Rules (each fails the check):
  1. Tests changed: backend/app/ or frontend/src/ changed, but nothing under backend/tests/,
     frontend/src/**/*.test.* or frontend/e2e/. Override: `[skip-tests-check]` in the title plus a reason
     in the body.
  2. Isolation changed: backend/migrations/ changed, but nothing under backend/tests/isolation/ or
     backend/tests/scope/. Override: `[skip-isolation-check]` plus a reason.
  3. Forbidden files: .env, .secrets/, *.pem, *.key, *.p12, database dumps, node_modules. No override.
  4. ADR link: a new file under backend/app/providers/ without a docs/decisions/ link in the body.
  5. Channel issue link: a new file under backend/app/channels/ without an issue link in the body.
  6. PR size: more than 800 changed lines (excluding lock files, fixtures, generated docs).
     Override: `[large-pr]` plus a reason.
  7. Template completed: required checkboxes unchecked, or an empty "How to Verify" section.

A reason is written in the body as `[tag] <reason of at least 10 characters>` or `[tag]: <reason>`.

Usage (CI passes the PR title, body and base SHA):
    check-contribution-guardrails.py --base <sha> [--title T] [--body B | --body-file F]
    check-contribution-guardrails.py --files a b c [--added a] [--changed-lines N] ...   (manual / tests)
PR_TITLE, PR_BODY and BASE_SHA environment variables are used when the options are not given.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import re
import subprocess
import sys
from pathlib import PurePosixPath

MAX_CHANGED_LINES = 800

FORBIDDEN_NAME_PATTERNS = ("*.pem", "*.key", "*.p12", "*.pfx", "*.dump", "*.sql.gz", "*.pgdump")
FORBIDDEN_ENV = re.compile(r"^\.env(\..+)?$")
ALLOWED_ENV = {".env.example"}
FORBIDDEN_DIRS = {".secrets", "node_modules"}

SIZE_EXCLUDED_NAMES = {"uv.lock", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "poetry.lock"}
SIZE_EXCLUDED_DIRS = ("fixtures", "__snapshots__", "cassettes")
SIZE_EXCLUDED_PREFIXES = ("docs/reference/",)

# Checklist items in .github/pull_request_template.md that must be ticked on every PR.
REQUIRED_BOXES = ("Data Hygiene", "Contributor License Agreement")
ADR_LINK = re.compile(r"docs/decisions/[A-Za-z0-9][\w.-]*")  # a specific ADR, not the template's hint
ISSUE_LINK = re.compile(r"(?:^|\s|\()(?:#\d+|https://github\.com/[^/\s]+/[^/\s]+/issues/\d+)")


# ------------------------------------------------------------------ helpers


def has_tag(text: str, tag: str) -> bool:
    return f"[{tag}]" in text.lower()


def has_reason(body: str, tag: str) -> bool:
    return bool(re.search(rf"\[{re.escape(tag)}\]\s*[:\-]?\s*\S.{{9,}}", body, re.IGNORECASE))


def override(title: str, body: str, tag: str, title_only: bool = False) -> str | None:
    """None when the override is valid; otherwise an explanation (or '' when no tag was used)."""
    tagged = has_tag(title, tag) or (not title_only and has_tag(body, tag))
    if not tagged:
        return ""
    if has_reason(body, tag):
        return None
    return f"[{tag}] is used but the PR body gives no reason (write '[{tag}] <reason>' in the body)."


# ------------------------------------------------------------------ rules


def check_forbidden_files(files: list[str]) -> list[str]:
    violations: list[str] = []
    for f in files:
        path = PurePosixPath(f)
        name = path.name
        if FORBIDDEN_DIRS.intersection(path.parts[:-1]) or name in FORBIDDEN_DIRS:
            violations.append(f"Forbidden file: {f} (.secrets/ and node_modules/ are never committed)")
        elif FORBIDDEN_ENV.match(name) and name not in ALLOWED_ENV:
            violations.append(f"Forbidden file: {f} (environment files are never committed)")
        elif any(fnmatch.fnmatch(name.lower(), p) for p in FORBIDDEN_NAME_PATTERNS):
            violations.append(
                f"Forbidden file: {f} (keys, certificates and database dumps are never committed)"
            )
    return violations


def is_test_file(f: str) -> bool:
    return f.startswith(("backend/tests/", "frontend/e2e/")) or (
        f.startswith("frontend/src/") and ".test." in PurePosixPath(f).name
    )


def check_tests_changed(files: list[str], title: str, body: str) -> list[str]:
    code_changed = any(f.startswith(("backend/app/", "frontend/src/")) and not is_test_file(f) for f in files)
    if not code_changed or any(is_test_file(f) for f in files):
        return []
    problem = override(title, body, "skip-tests-check", title_only=True)
    if problem is None:
        return []
    return [
        problem
        or "backend/app/ or frontend/src/ changed but no test changed. Add tests, or put "
        "[skip-tests-check] in the title with a reason in the body (docs-only or behavior-neutral refactor)."
    ]


def check_isolation(files: list[str], title: str, body: str) -> list[str]:
    if not any(f.startswith("backend/migrations/") for f in files):
        return []
    if any(f.startswith(("backend/tests/isolation/", "backend/tests/scope/")) for f in files):
        return []
    problem = override(title, body, "skip-isolation-check")
    if problem is None:
        return []
    return [
        problem
        or "backend/migrations/ changed but no isolation or scope test changed (master plan B10, C4.8). "
        "Add one, or use [skip-isolation-check] with a reason (for example, an index-only migration)."
    ]


def _is_code(f: str, prefix: str) -> bool:
    return f.startswith(prefix) and PurePosixPath(f).name != "README.md"


def check_provider_adr(added: list[str], body: str) -> list[str]:
    if any(_is_code(f, "backend/app/providers/") for f in added) and not ADR_LINK.search(body):
        return ["New file under backend/app/providers/ but the PR body has no docs/decisions/ ADR link (B3)."]
    return []


def check_channel_issue(added: list[str], body: str) -> list[str]:
    if any(_is_code(f, "backend/app/channels/") for f in added) and not ISSUE_LINK.search(body):
        return ["New file under backend/app/channels/ but the PR body has no issue link (#N or issue URL)."]
    return []


def counts_for_size(f: str) -> bool:
    path = PurePosixPath(f)
    if path.name in SIZE_EXCLUDED_NAMES or path.name.endswith(".lock"):
        return False
    if any(part in SIZE_EXCLUDED_DIRS for part in path.parts[:-1]):
        return False
    return not f.startswith(SIZE_EXCLUDED_PREFIXES)


def check_size(changed_lines: int | None, title: str, body: str) -> list[str]:
    if changed_lines is None or changed_lines <= MAX_CHANGED_LINES:
        return []
    problem = override(title, body, "large-pr")
    if problem is None:
        return []
    return [
        problem
        or f"PR changes {changed_lines} lines (limit {MAX_CHANGED_LINES}, excluding lock files, fixtures and "
        "generated docs). Split it, or use [large-pr] with a reason."
    ]


def _section(body: str, heading_word: str) -> str | None:
    m = re.search(rf"^#+\s*(?:\d+\.\s*)?{heading_word}\b.*$", body, re.IGNORECASE | re.MULTILINE)
    if not m:
        return None
    rest = body[m.end() :]
    nxt = re.search(r"^#+\s", rest, re.MULTILINE)
    return rest[: nxt.start()] if nxt else rest


def check_template(body: str) -> list[str]:
    problems: list[str] = []
    for label in REQUIRED_BOXES:
        box = re.search(rf"^\s*[-*]\s*\[( |x|X)\][^\n]*{re.escape(label)}", body, re.MULTILINE)
        if not box:
            problems.append(f"PR template: required checklist item '{label}' is missing.")
        elif box.group(1) == " ":
            problems.append(f"PR template: required checklist item '{label}' is not ticked.")
    verify = _section(body, "How to Verify")
    if verify is None:
        problems.append("PR template: the 'How to Verify' section is missing.")
    else:
        text = re.sub(r"<!--.*?-->", "", verify, flags=re.DOTALL)
        text = re.sub(r"^\s*```\w*\s*$", "", text, flags=re.MULTILINE)
        if not text.strip():
            problems.append("PR template: the 'How to Verify' section is empty.")
    return problems


# ------------------------------------------------------------------ git


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def changes_from_git(base: str) -> tuple[list[str], list[str], int]:
    rng = f"{base}...HEAD"
    files: list[str] = []
    added: list[str] = []
    for line in git("diff", "--name-status", "--no-renames", rng).splitlines():
        status, _, path = line.partition("\t")
        if not path:
            continue
        files.append(path)
        if status.startswith("A"):
            added.append(path)
    lines = 0
    for line in git("diff", "--numstat", "--no-renames", rng).splitlines():
        ins, dele, path = (line.split("\t", 2) + ["", "", ""])[:3]
        if ins == "-" or not counts_for_size(path):
            continue  # binary file or excluded from the size rule
        lines += int(ins) + int(dele)
    return files, added, lines


# ------------------------------------------------------------------ main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check PR contribution guardrails (master plan C9.4)")
    parser.add_argument("--title", default=os.environ.get("PR_TITLE", ""))
    parser.add_argument("--body", default=None)
    parser.add_argument("--body-file", default=None)
    parser.add_argument("--base", default=os.environ.get("BASE_SHA", ""), help="base commit SHA of the PR")
    parser.add_argument("--files", nargs="*", default=None, help="changed files (instead of --base)")
    parser.add_argument("--added", nargs="*", default=None, help="new files among --files (default: all)")
    parser.add_argument("--changed-lines", type=int, default=None, help="changed lines (with --files)")
    args = parser.parse_args(argv)

    if args.body_file:
        with open(args.body_file, encoding="utf-8") as fh:
            body = fh.read()
    else:
        body = args.body if args.body is not None else os.environ.get("PR_BODY", "")
    title = args.title

    if args.files is not None:
        files = [f.replace("\\", "/") for f in args.files]
        added = [f.replace("\\", "/") for f in args.added] if args.added is not None else files
        changed_lines = args.changed_lines
    elif args.base:
        try:
            files, added, changed_lines = changes_from_git(args.base)
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            sys.stderr.write(f"Could not diff against base {args.base}: {exc}\n")
            return 2
    else:
        sys.stderr.write("Give --base <sha> (or BASE_SHA), or --files.\n")
        return 2

    problems: list[str] = []
    problems += check_forbidden_files(files)
    problems += check_tests_changed(files, title, body)
    problems += check_isolation(files, title, body)
    problems += check_provider_adr(added, body)
    problems += check_channel_issue(added, body)
    problems += check_size(changed_lines, title, body)
    problems += check_template(body)

    if problems:
        sys.stderr.write(f"Contribution guardrails failed ({len(problems)} violation(s)):\n")
        for p in problems:
            sys.stderr.write(f"  - {p}\n")
        return 1
    print(f"Contribution guardrails passed ({len(files)} changed file(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
