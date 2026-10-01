#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Fail on broken relative links in the repository's Markdown files (master plan M1.2-T10, §C3.2).

Checks `[text](target)` and `[text]: target` links whose target is a relative path: the file or
directory must exist. External links (http, https, mailto) and pure `#anchor` links are not checked
here (external links are checked in CI). Code spans and fenced code blocks are ignored.

Usage:
    check-docs-links.py            check every *.md in the repository (git-ignored trees skipped)
    check-docs-links.py PATH...    check these files or directories
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

REPO_ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}
INLINE_LINK = re.compile(r"!?\[[^\]\n]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
REF_LINK = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*<?(\S+?)>?(?:\s+.*)?$", re.MULTILINE)
EXTERNAL = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//)", re.IGNORECASE)


def markdown_files(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if root.is_file():
            files.append(root)
            continue
        for path in root.rglob("*.md"):
            if not SKIP_DIRS.intersection(path.relative_to(REPO_ROOT).parts):
                files.append(path)
    return sorted(files)


def strip_code(text: str) -> str:
    text = re.sub(r"^(```|~~~).*?^\1[^\n]*$", "", text, flags=re.DOTALL | re.MULTILINE)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    return re.sub(r"`[^`\n]*`", "", text)


def check_file(path: Path) -> list[str]:
    text = strip_code(path.read_text(encoding="utf-8", errors="replace"))
    problems: list[str] = []
    rel = path.relative_to(REPO_ROOT).as_posix()
    targets = INLINE_LINK.findall(text) + REF_LINK.findall(text)
    for target in targets:
        if EXTERNAL.match(target) or target.startswith("#"):
            continue
        file_part = unquote(target.split("#", 1)[0].split("?", 1)[0])
        if not file_part:
            continue
        base = REPO_ROOT if file_part.startswith("/") else path.parent
        resolved = (base / file_part.lstrip("/")).resolve()
        if not resolved.exists():
            problems.append(f"{rel}: broken link -> {target}")
    return problems


def main(argv: list[str]) -> int:
    roots = [Path(a).resolve() for a in argv] if argv else [REPO_ROOT]
    files = markdown_files(roots)
    problems: list[str] = []
    for f in files:
        problems.extend(check_file(f))
    if problems:
        sys.stderr.write(f"Docs link check failed with {len(problems)} broken link(s):\n")
        for p in problems:
            sys.stderr.write(f"  {p}\n")
        return 1
    print(f"Docs link check passed ({len(files)} Markdown file(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
