"""Test fixtures: a throwaway git repo with the real .claude/hooks and loop.json."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1]
CLAUDE_DIR = HOOKS.parent


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


@pytest.fixture()
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "assetflow"
    (root / ".claude").mkdir(parents=True)
    shutil.copytree(HOOKS, root / ".claude" / "hooks", ignore=shutil.ignore_patterns("tests", "__pycache__"))
    shutil.copy(CLAUDE_DIR / "loop.json", root / ".claude" / "loop.json")
    (root / ".gitignore").write_text(".claude/state/\n__pycache__/\n")
    (root / "backend" / "app" / "modules" / "assets").mkdir(parents=True)
    (root / "backend" / "app" / "modules" / "assets" / "service.py").write_text("x = 1\n")
    (root / "docs").mkdir()
    (root / "docs" / "README.md").write_text("docs\n")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "chore: init")
    _git(root, "checkout", "-q", "-b", "feat/M1.1-T1-test")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    for flag in ("ASSETFLOW_GATE", "ASSETFLOW_OFFLIMITS", "ASSETFLOW_PLAN_AUTOPASS", "ASSETFLOW_SHIP_AUTOPASS"):
        monkeypatch.delenv(flag, raising=False)
    return root


def run_hook(repo: Path, name: str, payload: dict, env: dict | None = None) -> subprocess.CompletedProcess:
    e = {**os.environ, "CLAUDE_PROJECT_DIR": str(repo), **(env or {})}
    return subprocess.run(
        [sys.executable, str(repo / ".claude" / "hooks" / name)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=repo,
        env=e,
    )


def af(repo: Path, *args: str, stdin: str = "", env: dict | None = None) -> subprocess.CompletedProcess:
    e = {**os.environ, "CLAUDE_PROJECT_DIR": str(repo), **(env or {})}
    return subprocess.run(
        [sys.executable, str(repo / ".claude" / "hooks" / "af.py"), *args],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=repo,
        env=e,
    )


PLAN = {
    "task_id": "M1.1-T1",
    "title": "Assets service",
    "commit_type": "feat",
    "acceptance_criteria": [{"id": "AC1", "text": "works", "verify": "make verify"}],
    "scope_paths": ["backend/app/modules/assets/", "backend/tests/", "docs/"],
}


def approve_plan(repo: Path) -> None:
    assert af(repo, "plan", "set", stdin=json.dumps(PLAN)).returncode == 0
    r = run_hook(repo, "approval_gate.py", {"prompt": "approve-plan"})
    assert r.returncode == 0, r.stderr
