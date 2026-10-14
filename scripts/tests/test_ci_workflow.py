# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Static checks of .github/workflows/ci.yml and the Makefile targets it calls (AF-010, AF-044).

Run: make test-scripts
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOW = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
MAKEFILE = (ROOT / "Makefile").read_text(encoding="utf-8")


def _filters() -> dict[str, list[str]]:
    steps: list[dict[str, Any]] = WORKFLOW["jobs"]["changes"]["steps"]
    step = next(s for s in steps if s.get("id") == "filter")
    return yaml.safe_load(step["with"]["filters"])


def test_the_contract_job_also_runs_for_core_and_backend_tests() -> None:
    filters = _filters()
    assert {"backend/app/core/**", "backend/tests/**"} <= set(filters["contract"])
    assert "backend/app/providers/**" in filters["providers"]
    assert "backend/app/channels/**" in filters["channels"]
    condition = WORKFLOW["jobs"]["contract"]["if"]
    for output in ("providers", "channels", "contract"):
        assert f"needs.changes.outputs.{output} == 'true'" in condition
    assert "contract" in WORKFLOW["jobs"]["changes"]["outputs"]


def test_ci_quality_runs_the_empty_suite_guard() -> None:
    line = next(line for line in MAKEFILE.splitlines() if line.startswith("ci-quality:"))
    assert "check-test-suites" in line.split("##")[0].split()


def test_an_empty_suite_is_a_failure_in_ci_not_a_skip() -> None:
    macro = MAKEFILE.split("define pytest_suite", 1)[1].split("endef", 1)[0]
    assert "-eq 5" in macro and '[ -n "$$CI" ]' in macro
    assert macro.index('[ -n "$$CI" ]') < macro.index("SKIPPED")
