# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Unit tests for OWASP ASVS 5.0 L2 checklist generator (§B11.7, M1.6-T9)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GEN_SCRIPT = REPO_ROOT / "scripts" / "gen-asvs-checklist.py"
ASVS_JSON = REPO_ROOT / "docs" / "security" / "asvs" / "asvs-5.0.v5.0.0.json"
CHECKLIST_MD = REPO_ROOT / "docs" / "security" / "asvs-l2.md"


def test_gen_asvs_checklist_check_mode_succeeds() -> None:
    res = subprocess.run(
        [sys.executable, str(GEN_SCRIPT), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, f"Check mode failed: {res.stderr}\n{res.stdout}"
    assert "asvs-l2 check: up to date." in res.stdout


def test_every_asvs_requirement_present_in_markdown() -> None:
    with ASVS_JSON.open("r", encoding="utf-8") as f:
        data = json.load(f)
    reqs = data.get("requirements", [])
    assert len(reqs) > 0

    content = CHECKLIST_MD.read_text(encoding="utf-8")
    for req in reqs:
        assert req["id"] in content, f"Requirement {req['id']} missing from asvs-l2.md"
