#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Fail when a test suite directory is missing or holds no test file (AF-010).

`make test-*` treats "pytest collected nothing" (exit code 5) as a SKIPPED placeholder so a
fresh checkout still passes. That must never happen in CI: a suite whose tests were deleted, moved
or renamed would then turn green by running nothing. CI runs this check before the suites, and the
Makefile also turns exit code 5 into a failure when the `CI` environment variable is set.

Usage:
    python scripts/check-test-suites.py [DIR ...]      default: the backend suites CI runs

A directory counts as non-empty when it holds at least one ``test_*.py`` or ``*_test.py`` file
anywhere below it. Standard library only.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SUITES = (
    "backend/tests/unit",
    "backend/tests/integration",
    "backend/tests/authz_matrix",
    "backend/tests/isolation",
    "backend/tests/scope",
    "backend/tests/contract",
    "backend/tests/e2e_api",
)


def test_files(directory: Path) -> list[Path]:
    """Every pytest test file below ``directory`` (empty when it does not exist)."""
    if not directory.is_dir():
        return []
    return sorted({*directory.rglob("test_*.py"), *directory.rglob("*_test.py")})


def empty_suites(directories: list[Path]) -> list[Path]:
    return [d for d in directories if not test_files(d)]


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    directories = [Path(a) if Path(a).is_absolute() else REPO_ROOT / a for a in (args or DEFAULT_SUITES)]
    empty = empty_suites(directories)
    for directory in empty:
        print(f"error: test suite {directory} is missing or contains no test files", file=sys.stderr)
    if empty:
        print(
            "A suite that collects nothing must fail CI, not pass: restore the tests or remove the "
            "suite from the CI targets and from scripts/check-test-suites.py in the same change.",
            file=sys.stderr,
        )
        return 1
    print(f"check-test-suites: {len(directories)} suites, all with tests.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
