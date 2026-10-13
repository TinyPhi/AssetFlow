# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""scripts/check-test-suites.py: an empty or missing test directory fails (AF-010).

Run: make test-scripts
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "check-test-suites.py"
_spec = importlib.util.spec_from_file_location("check_test_suites", SCRIPT)
assert _spec is not None and _spec.loader is not None
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


def test_a_directory_with_a_test_file_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "unit").mkdir()
    (tmp_path / "unit" / "test_x.py").write_text("def test_x(): pass\n")
    assert guard.main([str(tmp_path / "unit")]) == 0
    assert "all with tests" in capsys.readouterr().out


def test_an_empty_directory_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "scope").mkdir()
    assert guard.main([str(tmp_path / "scope")]) == 1
    assert "contains no test files" in capsys.readouterr().err


def test_a_directory_with_only_helpers_fails(tmp_path: Path) -> None:
    (tmp_path / "contract").mkdir()
    (tmp_path / "contract" / "conftest.py").write_text("")
    (tmp_path / "contract" / "README.md").write_text("")
    assert guard.main([str(tmp_path / "contract")]) == 1


def test_a_missing_directory_fails(tmp_path: Path) -> None:
    assert guard.main([str(tmp_path / "nope")]) == 1


def test_nested_test_files_count(tmp_path: Path) -> None:
    (tmp_path / "contract" / "auth").mkdir(parents=True)
    (tmp_path / "contract" / "auth" / "test_oidc.py").write_text("")
    assert guard.main([str(tmp_path / "contract")]) == 0


def test_one_empty_suite_among_good_ones_fails(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "test_a.py").write_text("")
    (tmp_path / "b").mkdir()
    assert guard.main([str(tmp_path / "a"), str(tmp_path / "b")]) == 1


def test_the_repository_suites_all_have_tests() -> None:
    assert guard.main([]) == 0
