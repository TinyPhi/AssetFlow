# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""scripts/check-mistakes-log.py: kinds in Mistake_Learn.md, traces in Mistake_Traces.md, linked both ways.

Run: make test-scripts
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import re
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "check-mistakes-log.py"
REPO = SCRIPT.parent.parent
_spec = importlib.util.spec_from_file_location("check_mistakes_log", SCRIPT)
assert _spec is not None and _spec.loader is not None
mlog: Any = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mlog  # @dataclass looks its module up while the class is built
_spec.loader.exec_module(mlog)

LEARN = f"# Mistake_Learn.md\n\nIntro.\n\n## Active\n\n{mlog.LEARN_HEADER}\n{mlog.LEARN_RULE}\n"
TRACES = (
    f"# Mistake_Traces.md\n\n## Retired kinds\n\n{mlog.RETIRED_HEADER}\n{mlog.RETIRED_RULE}\n\n## Traces\n"
)
TRACE = ["--where", "PR 1", "--trigger", "doing a task", "--cause", "a shortcut", "--fix", "fixed"]
TRACE += ["--verified", "make verify green", "--date", "2026-10-08"]


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "Mistake_Learn.md").write_text(LEARN, encoding="utf-8")
    (tmp_path / "Mistake_Traces.md").write_text(TRACES, encoding="utf-8")
    (tmp_path / "Makefile").write_text("lint:\n\tpython scripts/check-x.py\n", encoding="utf-8")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "check-x.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(mlog, "ROOT", tmp_path)
    return tmp_path


def run(*argv: str) -> int:
    code: int = mlog.main(list(argv))
    return code


def new(rule: str, check: str = "", *extra: str) -> int:
    args = ["new", "--area", "commits", "--rule", rule, "--check", check or f"check {rule}", "--why", "why"]
    return run(*args, *TRACE, *extra)


def problems(root: Path) -> list[str]:
    result: list[str] = mlog.find_problems(mlog.Log(root))
    return result


def learn(root: Path) -> str:
    return (root / "Mistake_Learn.md").read_text(encoding="utf-8")


def traces(root: Path) -> str:
    return (root / "Mistake_Traces.md").read_text(encoding="utf-8")


def test_repository_log_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mlog, "ROOT", REPO)
    assert problems(REPO) == []


def test_new_writes_a_kind_and_a_trace_linked_both_ways(repo: Path) -> None:
    assert new("Use allowed commit types") == 0
    trace_id = re.search(r"T-\d{8}-[0-9a-f]{4}", traces(repo))
    assert trace_id is not None
    tid = trace_id.group(0)
    assert f"[{tid}](Mistake_Traces.md#{tid.lower()})" in learn(repo)
    assert f'<a id="{tid.lower()}"></a>{tid} · 2026-10-08 · [M-001](Mistake_Learn.md#m-001)' in traces(repo)
    assert '<a id="m-001"></a>M-001' in learn(repo)
    assert problems(repo) == []


def test_new_refuses_a_similar_kind(repo: Path) -> None:
    new("Never log a secret value")
    assert new("Never log secret values", "other check") == 1
    assert new("Never log secret values", "other check", "--force") == 0


def test_seen_adds_a_trace_with_its_context(repo: Path) -> None:
    new("Use allowed commit types")
    assert run("seen", "M-001", "--where", "PR 2", "--trigger", "rebasing", "--cause", "guessed a type") == 0
    text = traces(repo)
    assert "- **Trigger:** rebasing" in text and "- **Root cause:** guessed a type" in text
    assert "- **Fix:** pending" in text
    assert learn(repo).count("Mistake_Traces.md#t-") == 2
    assert problems(repo) == []


def test_trace_ids_never_collide(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A drawn id already in the log is skipped. Deterministic: 50 real draws from 65,536 values
    collided about once in 50 runs (PR #351 review)."""
    log = mlog.Log(repo)
    log.traces["T-20261008-abcd"] = mlog.Trace(ident="T-20261008-abcd", date="2026-10-08", kind="M-001")
    draws = iter(["abcd", "abcd", "1234"])
    monkeypatch.setattr(mlog.secrets, "token_hex", lambda _n: next(draws))
    assert log.new_trace_id("2026-10-08") == "T-20261008-1234"


def test_third_trace_demands_a_tooling_check(repo: Path) -> None:
    new("Use allowed commit types")
    run("seen", "M-001", *TRACE)
    run("seen", "M-001", *TRACE)
    assert any("not sticking" in p for p in problems(repo))


def test_retire_moves_the_kind_and_keeps_its_traces(repo: Path) -> None:
    new("Use allowed commit types")
    assert run("retire", "M-001", "--enforced-by", "scripts/check-x.py") == 0
    assert "M-001" not in learn(repo).split("## Active")[1]
    assert "| M-001 | enforced |" in traces(repo)
    assert "[M-001](#retired-kinds)" in traces(repo)
    assert problems(repo) == []


def test_enforcer_must_run_in_ci(repo: Path) -> None:
    new("Use allowed commit types")
    (repo / "scripts" / "unused.py").write_text("", encoding="utf-8")
    run("retire", "M-001", "--enforced-by", "scripts/unused.py")
    assert any("nothing guarantees it runs" in p for p in problems(repo))


def test_a_repeat_reactivates_the_same_kind(repo: Path) -> None:
    new("Use allowed commit types")
    run("retire", "M-001", "--dormant")
    run("seen", "M-001", *TRACE)
    assert '<a id="m-001"></a>M-001' in learn(repo)
    assert "M-002" not in learn(repo) + traces(repo)


def test_hand_edited_links_are_caught(repo: Path) -> None:
    new("Use allowed commit types")
    path = repo / "Mistake_Learn.md"
    path.write_text(re.sub(r"\[T-[^]]+\]\([^)]+\)", "-", learn(repo)), encoding="utf-8")
    assert any("do not match its traces" in p for p in problems(repo))


def test_a_trace_doubled_by_a_union_merge_is_caught(repo: Path) -> None:
    new("Use allowed commit types")
    block = traces(repo).split("## Traces\n\n", 1)[1]
    (repo / "Mistake_Traces.md").write_text(traces(repo) + "\n" + block, encoding="utf-8")
    assert any("used twice" in p for p in problems(repo))


def test_empty_trace_field_is_caught(repo: Path) -> None:
    new("Use allowed commit types")
    path = repo / "Mistake_Traces.md"
    path.write_text(
        traces(repo).replace("- **Root cause:** a shortcut", "- **Root cause:**"), encoding="utf-8"
    )
    assert any("empty Root cause" in p for p in problems(repo))


def test_size_limits(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mlog, "MAX_ACTIVE", 2)
    monkeypatch.setattr(mlog, "MAX_TRACE_LINES", 10)
    for n in range(3):
        new(f"Rule about topic{n}", f"cmd {n}", "--force")
    found = problems(repo)
    assert any("active kinds (max 2)" in p for p in found)
    assert any("run `archive`" in p for p in found)


def test_archive_moves_old_traces_of_retired_kinds(repo: Path) -> None:
    run(
        "new",
        "--area",
        "commits",
        "--rule",
        "Use allowed commit types",
        "--check",
        "c",
        "--why",
        "w",
        *TRACE[:-1],
        "2024-05-01",
    )
    run("retire", "M-001", "--dormant")
    log = mlog.Log(repo)
    assert mlog.cmd_archive(log, dt.date(2026, 10, 8)) == 0
    archived = (repo / "Mistake_Traces_archive" / "2024.md").read_text(encoding="utf-8")
    assert "· 2024-05-01 · [M-001](../Mistake_Traces.md#retired-kinds)" in archived
    assert "Mistake_Traces_archive/2024.md#t-20240501-" in traces(repo)
    assert problems(repo) == []


def test_report_lists_repeats_and_open_fixes(repo: Path) -> None:
    new("Use allowed commit types")
    run("seen", "M-001", "--where", "PR 2", "--trigger", "t", "--cause", "c")
    text: str = mlog.report(mlog.Log(repo))
    assert "M-001 x2" in text
    assert "PR 2" in text.split("Open")[1]


def test_find_searches_causes_of_retired_kinds(repo: Path) -> None:
    new("Use allowed commit types")
    run("retire", "M-001", "--dormant")
    ranked = mlog.find_similar(mlog.Log(repo), "a shortcut in commit types")
    assert ranked and ranked[0][1].ident == "M-001"


def test_stem_matches_word_forms() -> None:
    assert mlog.stem("logged") == mlog.stem("logs") == mlog.stem("logging") == "log"


def test_same_new_kind_id_on_two_branches_is_never_merged_silently(repo: Path) -> None:
    new("Use allowed commit types")
    row = next(line for line in learn(repo).splitlines() if "M-001" in line and "<a id" in line)
    clash = row.replace("Use allowed commit types", "Seed data through fixtures")
    (repo / "Mistake_Learn.md").write_text(learn(repo) + clash + "\n", encoding="utf-8")
    assert any("used by two different kinds" in p for p in problems(repo))
    assert run("sync") == 1
