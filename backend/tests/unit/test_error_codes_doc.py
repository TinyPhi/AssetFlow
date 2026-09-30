# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""docs/reference/error-codes.md must match the error registry (regenerate: scripts/gen-error-codes.py)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from app.core.problems import ERROR_REGISTRY

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "gen-error-codes.py"
DOC = REPO_ROOT / "docs" / "reference" / "error-codes.md"


def _generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gen_error_codes", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_error_codes_doc_is_current() -> None:
    expected = _generator().render()
    assert DOC.read_text(encoding="utf-8") == expected, "stale: run python scripts/gen-error-codes.py"


def test_every_code_has_an_anchor() -> None:
    text = DOC.read_text(encoding="utf-8")
    for cls in ERROR_REGISTRY:
        assert f'<a id="{cls.code}"></a>' in text


def test_old_errors_reference_is_gone() -> None:
    assert not (REPO_ROOT / "docs" / "reference" / "errors.md").exists()
