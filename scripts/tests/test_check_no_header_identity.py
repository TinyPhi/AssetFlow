# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""scripts/check-no-header-identity.py: no identity is read from request headers (NEW-5).

Run: make test-scripts
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "check-no-header-identity.py"
_spec = importlib.util.spec_from_file_location("check_no_header_identity", SCRIPT)
assert _spec is not None and _spec.loader is not None
check: Any = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)


@pytest.mark.parametrize(
    "line",
    [
        'role = request.headers.get("x-role", "admin")',
        "mid = request.headers.get('x-member-id')",
        'org = request.headers["x-organization-id"]',
        'if request.headers.get("X-Platform-Admin") == "true":',
    ],
)
def test_identity_header_reads_are_flagged(tmp_path: Path, line: str) -> None:
    (tmp_path / "route.py").write_text(f"def f(request):\n    {line}\n", encoding="utf-8")
    assert len(check.find_violations(tmp_path)) == 1
    assert check.main([str(tmp_path)]) == 1


def test_other_headers_pass(tmp_path: Path) -> None:
    (tmp_path / "route.py").write_text('v = request.headers.get("x-request-id")\n', encoding="utf-8")
    assert check.main([str(tmp_path)]) == 0


def test_the_application_has_no_identity_header_reads() -> None:
    assert check.main([]) == 0
