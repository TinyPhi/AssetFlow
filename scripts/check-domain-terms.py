#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Fail when a forbidden domain, company or legacy term appears in core code (§B10, §C12).

Denylist: scripts/check-domain-terms.txt (master plan §C12 plus the P0-04 inventory).
Scope: backend/app/, frontend/src/ and config/ (for example config/organizations/),
case-insensitive, whole words only.
Excluded: translation files (locales/, translations/, i18n/), tests of this check itself, and the
two config folders where industry words are allowed (§C12): config/domains/ (domain templates)
and config/templates/ (notification and document templates).

Usage:
    check-domain-terms.py            scan the default directories
    check-domain-terms.py PATH...    scan only these files or directories (must be inside the scope)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DENYLIST_FILE = REPO_ROOT / "scripts" / "check-domain-terms.txt"
SCOPE_DIRS = (
    REPO_ROOT / "backend" / "app",
    REPO_ROOT / "frontend" / "src",
    REPO_ROOT / "config",
    REPO_ROOT / "docs" / "specs",
)
# Industry words may appear in domain templates and notification templates (§C12).
ALLOWED_DIRS = (REPO_ROOT / "config" / "domains", REPO_ROOT / "config" / "templates")
TEXT_SUFFIXES = {
    ".py",
    ".pyi",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".json",
    ".css",
    ".scss",
    ".html",
    ".sql",
    ".yaml",
    ".yml",
    ".toml",
    ".md",
    ".txt",
}
EXCLUDED_DIR_NAMES = {"locales", "translations", "i18n", "__pycache__", "node_modules"}
SELF_TEST_PREFIXES = ("test_check_domain_terms", "check-domain-terms.test", "check_domain_terms.test")


def load_terms(path: Path) -> list[str]:
    terms: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            terms.append(line)
    return terms


def build_pattern(terms: list[str]) -> re.Pattern[str]:
    # Whole word, case-insensitive. Underscores and camelCase humps count as word breaks, so
    # identifiers such as `employee_id` and `employeeId` are caught, while `workstation` is not.
    alternatives = "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
    return re.compile(rf"(?<![A-Za-z0-9])(?i:{alternatives})(?![a-z0-9])")


def in_scope(path: Path) -> bool:
    return any(path == d or d in path.parents for d in SCOPE_DIRS)


def is_excluded(path: Path) -> bool:
    if EXCLUDED_DIR_NAMES.intersection(path.parts):
        return True
    if any(path == d or d in path.parents for d in ALLOWED_DIRS):
        return True
    return path.name.startswith(SELF_TEST_PREFIXES)


def iter_files(roots: list[Path]):
    for root in roots:
        if root.is_file():
            candidates = [root]
        elif root.is_dir():
            candidates = sorted(p for p in root.rglob("*") if p.is_file())
        else:
            continue
        for path in candidates:
            if path.suffix.lower() in TEXT_SUFFIXES and in_scope(path) and not is_excluded(path):
                yield path


def main(argv: list[str]) -> int:
    if not DENYLIST_FILE.is_file():
        sys.stderr.write(f"Denylist file not found: {DENYLIST_FILE}\n")
        return 2
    terms = load_terms(DENYLIST_FILE)
    if not terms:
        sys.stderr.write(f"Denylist is empty: {DENYLIST_FILE}\n")
        return 2
    pattern = build_pattern(terms)

    roots = [Path(a).resolve() for a in argv] if argv else list(SCOPE_DIRS)
    violations: list[str] = []
    for path in iter_files(roots):
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            sys.stderr.write(f"Could not read {path}: {exc}\n")
            return 2
        rel = path.relative_to(REPO_ROOT).as_posix()
        for line_no, line in enumerate(content.splitlines(), start=1):
            for match in pattern.finditer(line):
                violations.append(f"{rel}:{line_no}: forbidden term '{match.group(0)}'")

    if violations:
        sys.stderr.write(f"Domain-terms check failed with {len(violations)} violation(s):\n")
        for v in violations:
            sys.stderr.write(f"  {v}\n")
        sys.stderr.write(
            "Use neutral terms (docs/tracker/domain-terms.md); industry words belong in config/domains/.\n"
        )
        return 1

    print("Domain-terms check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
