# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Unit tests for OWASP ASVS 5.0 L2 checklist generator (§B11.7, M1.6-T9)."""

from __future__ import annotations

import importlib.util
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


def _generator() -> object:
    spec = importlib.util.spec_from_file_location("gen_asvs_checklist", GEN_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_check_reports_met_or_partial_rows_citing_paths_that_do_not_exist(tmp_path: Path) -> None:
    """PR #357 review: MET rows cited tests that never existed and nothing caught it."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "real.py").write_text("async def test_real():\n    pass\n", encoding="utf-8")
    mapping = {
        "V1": {"status": "met", "code": "pkg/real.py", "test": "pkg/real.py::test_real"},
        "V2": {"status": "met", "code": "pkg/gone.py", "test": "-"},
        "V3": {"status": "partial", "code": "pkg/*.py", "test": "pkg/real.py::test_gone"},
        "V4": {"status": "met", "code": "nope/*.py", "test": "make config-validate"},
        "V5": {"status": "open", "code": "pkg/gone.py"},
        "V6": {"status": "met", "test": "pkg/real.py (injection attempt refused), frontend test suite"},
        "V7": {"status": "met", "test": "pkg/real.py pkg/also.py"},
    }
    missing = _generator().missing_evidence(mapping, tmp_path)  # type: ignore[attr-defined]
    assert missing == [
        "V2 code: pkg/gone.py",
        "V3 test: pkg/real.py::test_gone",
        "V4 code: nope/*.py",
        "V7 test: pkg/real.py pkg/also.py",
    ]


def test_every_cited_path_in_the_real_mapping_exists() -> None:
    generator = _generator()
    assert generator.missing_evidence(generator.load_mapping()) == []  # type: ignore[attr-defined]


def test_the_page_does_not_claim_to_be_the_full_asvs_5_list() -> None:
    content = CHECKLIST_MD.read_text(encoding="utf-8")
    assert "# OWASP ASVS 5.0 Level 2 Checklist" not in content
    assert "not** the complete OWASP ASVS 5.0 list" in content
