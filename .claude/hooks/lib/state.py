"""Shared helpers for the AssetFlow delivery-loop hooks.

All loop state lives in `.claude/state/<kind>/<branch-slug>.json` (git-ignored).
Every gate artifact is bound to `diff_sha`: a sha256 over the working-tree diff
against HEAD plus the contents of untracked files, so any later edit makes the
artifact stale.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

STATE_KINDS = (
    "plan",
    "verify",
    "review",
    "security",
    "docs",
    "ship-approval",
    "ship-ready",
    "claimed-done",
)
ONE_SHOT_KINDS = ("verify", "review", "security", "docs", "ship-approval", "ship-ready", "claimed-done")


# --------------------------------------------------------------------------- git


def git(*args: str, check: bool = False, cwd: Path | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd or repo_root()),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def git_bytes(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=str(repo_root()), capture_output=True).stdout


_ROOT: Path | None = None


def repo_root() -> Path:
    global _ROOT
    if _ROOT is None:
        env = os.environ.get("CLAUDE_PROJECT_DIR")
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=env or os.getcwd(),
            capture_output=True,
            text=True,
        )
        _ROOT = Path(out.stdout.strip() or env or os.getcwd()).resolve()
    return _ROOT


def branch() -> str:
    name = git("rev-parse", "--abbrev-ref", "HEAD").strip()
    return name or "detached"


def slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "-", name)


def head_sha() -> str:
    return git("rev-parse", "HEAD").strip()


def untracked_files() -> list[str]:
    return [p for p in git("ls-files", "--others", "--exclude-standard").splitlines() if p]


def changed_files() -> list[str]:
    """Files changed against HEAD (staged or not) plus untracked files."""
    tracked = [p for p in git("diff", "HEAD", "--name-only").splitlines() if p]
    return sorted(set(tracked) | set(untracked_files()))


def staged_files() -> list[str]:
    return [p for p in git("diff", "--cached", "--name-only").splitlines() if p]


def unstaged_files() -> list[str]:
    return [p for p in git("diff", "--name-only").splitlines() if p]


def diff_sha() -> str:
    """sha256 over every changed path and its working-tree bytes.

    Independent of staging: `git add` does not change it, any content edit does.
    Covers files changed against HEAD (staged or not), untracked files and deletions.
    """
    h = hashlib.sha256()
    h.update(head_sha().encode())
    root = repo_root()
    for rel in changed_files():
        h.update(b"\0" + rel.encode() + b"\0")
        try:
            h.update((root / rel).read_bytes())
        except OSError:
            h.update(b"<deleted>")
    return h.hexdigest()


def staged_tree_sha() -> str:
    return git("write-tree").strip()


# --------------------------------------------------------------------------- config


_CONFIG: dict[str, Any] | None = None


def config() -> dict[str, Any]:
    global _CONFIG
    if _CONFIG is None:
        path = repo_root() / ".claude" / "loop.json"
        _CONFIG = json.loads(path.read_text(encoding="utf-8"))
    return _CONFIG


def _any(patterns: list[str], path: str) -> bool:
    return any(re.search(p, path) for p in patterns)


def rel_path(path: str) -> str:
    """Normalize an absolute or relative path to repo-relative forward slashes."""
    if not path:
        return ""
    p = Path(path)
    if p.is_absolute():
        try:
            p = p.resolve().relative_to(repo_root())
        except ValueError:
            return str(p).replace("\\", "/")
    s = str(p).replace("\\", "/")
    return s[2:] if s.startswith("./") else s


def is_test(path: str) -> bool:
    return _any(config()["test_patterns"], path)


def is_source(path: str) -> bool:
    return _any(config()["source_patterns"], path) and not is_test(path)


def is_doc(path: str) -> bool:
    return _any(config()["doc_patterns"], path)


def is_security_path(path: str) -> bool:
    return _any(config()["security_paths"], path)


def is_migration(path: str) -> bool:
    return _any(config()["migration_patterns"], path)


def is_isolation_test(path: str) -> bool:
    return _any(config()["isolation_test_patterns"], path)


def module_key(path: str) -> str | None:
    """Area a source file belongs to, used to match it with a test.

    backend/app/modules/assets/x.py -> "assets"; backend/app/core/db.py -> "core";
    backend/app/providers/auth/oidc.py -> "auth"; frontend/src/features/assets/... -> "assets".
    """
    m = re.match(r"^backend/app/modules/([^/]+)/", path)
    if m:
        return m.group(1)
    m = re.match(r"^backend/app/(providers|channels|engines)/([^/.]+)", path)
    if m:
        return m.group(2)
    m = re.match(r"^backend/app/([^/.]+)", path)
    if m:
        return m.group(1)
    m = re.match(r"^backend/workers/([^/.]+)", path)
    if m:
        return m.group(1)
    m = re.match(r"^frontend/src/features/([^/]+)/", path)
    if m:
        return m.group(1)
    return None


# --------------------------------------------------------------------------- state


def state_dir() -> Path:
    d = repo_root() / ".claude" / "state"
    d.mkdir(parents=True, exist_ok=True)
    return d


def state_path(kind: str, branch_name: str | None = None) -> Path:
    if kind not in STATE_KINDS:
        raise ValueError(f"unknown state kind {kind!r}")
    d = state_dir() / kind
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{slug(branch_name or branch())}.json"


@contextmanager
def locked(kind: str, timeout: float = 5.0) -> Iterator[None]:
    """Cross-platform lock file so two sessions on one branch do not collide."""
    lock = state_path(kind).with_suffix(".lock")
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            if time.monotonic() > deadline:
                raise RuntimeError(f"state lock busy: {lock}") from None
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def read_state(kind: str) -> dict[str, Any] | None:
    path = state_path(kind)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_state(kind: str, data: dict[str, Any]) -> Path:
    path = state_path(kind)
    with locked(kind):
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
    return path


def delete_state(kind: str) -> None:
    try:
        state_path(kind).unlink()
    except FileNotFoundError:
        pass


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def age_minutes(iso: str) -> float:
    then = _dt.datetime.fromisoformat(iso)
    return (_dt.datetime.now(_dt.timezone.utc) - then).total_seconds() / 60


# --------------------------------------------------------------------------- flags and logging


def flag(name: str, value: str = "1") -> bool:
    return os.environ.get(name, "") == value


def log_bypass(name: str, detail: str) -> None:
    line = f"{now_iso()}\t{branch()}\t{name}\t{detail}\n"
    with open(state_dir() / "bypass.log", "a", encoding="utf-8") as f:
        f.write(line)


# --------------------------------------------------------------------------- hook I/O


def hook_input() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def block(message: str) -> None:
    """Exit 2: Claude Code blocks the tool call and shows the message to the model."""
    sys.stderr.write(f"[assetflow-loop] BLOCKED: {message}\n")
    sys.exit(2)


def allow() -> None:
    sys.exit(0)


def strip_quotes(command: str) -> str:
    """Remove quoted strings so `echo "git commit"` is not treated as a commit."""
    command = re.sub(r"'[^']*'", "''", command)
    command = re.sub(r'"(?:[^"\\]|\\.)*"', '""', command)
    return command
