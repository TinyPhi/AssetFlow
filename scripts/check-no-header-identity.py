#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Fail when backend/app reads an identity from a request header (NEW-5, §C5.4).

Who a caller is comes only from `AuthMiddleware`'s verified token. A route that reads
`headers.get("x-role")`, `x-member-id`, `x-organization-id`, `x-scope-type`, `x-scope-id`,
`x-org-unit-path`, `x-team-ids` or `x-platform-admin` lets an anonymous caller claim any role.
Tests supply a member through `tests/support/header_identity.py` instead.

Usage:
    python scripts/check-no-header-identity.py [ROOT ...]     (default: backend/app)

Standard library only.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

IDENTITY_HEADERS = (
    "x-role",
    "x-member-id",
    "x-organization-id",
    "x-scope-type",
    "x-scope-id",
    "x-org-unit-path",
    "x-team-ids",
    "x-platform-admin",
)
_PATTERN = re.compile(
    r"""headers(?:\.get|\[)\(?\s*['"](?:{})['"]""".format("|".join(IDENTITY_HEADERS)), re.IGNORECASE
)


def find_violations(root: Path) -> list[str]:
    """`path:line: text` for every identity-header read under ``root``."""
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if _PATTERN.search(line):
                found.append(f"{path}:{number}: {line.strip()}")
    return found


def main(argv: list[str]) -> int:
    roots = [Path(a) for a in argv] or [Path(__file__).resolve().parent.parent / "backend" / "app"]
    violations = [v for root in roots for v in find_violations(root)]
    for violation in violations:
        print(violation, file=sys.stderr)
    if violations:
        print(
            f"{len(violations)} identity-header read(s): identity comes from the token only", file=sys.stderr
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
