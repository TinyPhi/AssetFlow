"""Unit tests for the AssetFlow loop hooks. Run: python -m pytest .claude/hooks/tests"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from conftest import PLAN, af, approve_plan, run_hook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from approval_gate import parse  # noqa: E402
from af import parse_tracker, pick_next  # noqa: E402


def edit(repo: Path, rel: str) -> dict:
    return {"tool_name": "Edit", "tool_input": {"file_path": str(repo / rel)}}


def bash(cmd: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": cmd}}


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


# ------------------------------------------------------------------ approval keywords


def test_approval_keyword_parsing() -> None:
    assert parse("approve-plan") == "approve-plan"
    assert parse("ok, approve-ship") == "approve-ship"
    assert parse("Yes approve-plan looks good") == "approve-plan"
    assert parse("don't approve-plan yet") is None
    assert parse("why approve-ship?") is None
    assert parse("approve-plan?") is None
    assert parse("") is None


def test_plan_cannot_be_self_approved(repo: Path) -> None:
    assert af(repo, "plan", "set", stdin=json.dumps(PLAN)).returncode == 0
    r = af(repo, "plan", "approve")
    assert r.returncode != 0 and "HUMAN-ONLY" in r.stderr


def test_plan_requires_scope(repo: Path) -> None:
    bad = {**PLAN, "scope_paths": []}
    assert af(repo, "plan", "set", stdin=json.dumps(bad)).returncode != 0


# ------------------------------------------------------------------ edit gate


def test_source_edit_blocked_without_plan(repo: Path) -> None:
    r = run_hook(repo, "edit_gate.py", edit(repo, "backend/app/modules/assets/service.py"))
    assert r.returncode == 2 and "no plan" in r.stderr


def test_test_and_doc_edits_allowed_without_plan(repo: Path) -> None:
    assert run_hook(repo, "edit_gate.py", edit(repo, "backend/tests/unit/test_assets.py")).returncode == 0
    assert run_hook(repo, "edit_gate.py", edit(repo, "docs/guide.md")).returncode == 0


def test_source_edit_allowed_after_approval_and_scope_enforced(repo: Path) -> None:
    approve_plan(repo)
    assert run_hook(repo, "edit_gate.py", edit(repo, "backend/app/modules/assets/service.py")).returncode == 0
    r = run_hook(repo, "edit_gate.py", edit(repo, "backend/app/modules/maintenance/service.py"))
    assert r.returncode == 2 and "scope_paths" in r.stderr


def test_gate_bypass_is_logged(repo: Path) -> None:
    r = run_hook(repo, "edit_gate.py", edit(repo, "backend/app/core/db.py"), env={"ASSETFLOW_GATE": "off"})
    assert r.returncode == 0
    assert "ASSETFLOW_GATE=off" in (repo / ".claude" / "state" / "bypass.log").read_text()


# ------------------------------------------------------------------ protected paths


def test_env_files_never_editable(repo: Path) -> None:
    assert run_hook(repo, "protected_paths.py", edit(repo, ".env")).returncode == 2
    assert run_hook(repo, "protected_paths.py", edit(repo, "deploy/.env.production")).returncode == 2
    assert run_hook(repo, "protected_paths.py", edit(repo, ".env.example")).returncode == 0


def test_offlimits_needs_ack(repo: Path) -> None:
    payload = edit(repo, ".github/workflows/ci.yml")
    assert run_hook(repo, "protected_paths.py", payload).returncode == 2
    assert run_hook(repo, "protected_paths.py", payload, env={"ASSETFLOW_OFFLIMITS": "ack"}).returncode == 0


def test_no_edits_on_main(repo: Path) -> None:
    git(repo, "checkout", "-q", "main")
    r = run_hook(repo, "protected_paths.py", edit(repo, "docs/guide.md"))
    assert r.returncode == 2 and "main" in r.stderr


def test_merged_migration_is_immutable(repo: Path) -> None:
    mig = repo / "backend" / "migrations" / "versions" / "0001_init.py"
    mig.parent.mkdir(parents=True)
    mig.write_text("# m\n")
    git(repo, "checkout", "-q", "main")
    git(repo, "add", str(mig))
    git(repo, "commit", "-q", "-m", "feat(db): init")
    git(repo, "checkout", "-q", "-b", "feat/M1.4-T1-x")
    r = run_hook(repo, "protected_paths.py", edit(repo, "backend/migrations/versions/0001_init.py"))
    assert r.returncode == 2 and "merged" in r.stderr


# ------------------------------------------------------------------ destructive guard


def test_destructive_commands_blocked(repo: Path) -> None:
    for cmd in (
        "rm -rf /",
        "rm -rf .git",
        "git push --force origin x",
        "git push origin +main",
        "git commit --no-verify -m 'x'",
        "git reset --hard HEAD~1",
        "git add -A",
        "git add .",
        "git merge main",
        "gh pr merge 12",
        "psql -c 'x'; DROP TABLE assets",
    ):
        assert run_hook(repo, "destructive_guard.py", bash(cmd)).returncode == 2, cmd


def test_harmless_commands_allowed(repo: Path) -> None:
    for cmd in ('echo "rm -rf /"', "git merge-base main HEAD", "git add backend/app/x.py", "rm -rf ./build", "make verify"):
        assert run_hook(repo, "destructive_guard.py", bash(cmd)).returncode == 0, cmd


def test_shell_write_to_source_blocked_without_plan(repo: Path) -> None:
    r = run_hook(repo, "destructive_guard.py", bash("echo x > backend/app/modules/assets/service.py"))
    assert r.returncode == 2 and "shell write" in r.stderr
    assert run_hook(repo, "destructive_guard.py", bash("echo x > /tmp/scratch.txt")).returncode == 0


def test_state_cannot_be_forged_from_shell(repo: Path) -> None:
    r = run_hook(repo, "destructive_guard.py", bash("echo {} > .claude/state/review/x.json"))
    assert r.returncode == 2


# ------------------------------------------------------------------ tests rules


def test_review_requires_area_test(repo: Path) -> None:
    approve_plan(repo)
    (repo / "backend/app/modules/assets/service.py").write_text("x = 2\n")
    r = af(repo, "review", "set", stdin=json.dumps({"verdict": "approve", "dod_met": True}))
    assert r.returncode != 0 and "no test changed" in r.stdout


def test_fix_requires_repro_test(repo: Path) -> None:
    assert af(repo, "plan", "set", stdin=json.dumps({**PLAN, "commit_type": "fix"})).returncode == 0
    run_hook(repo, "approval_gate.py", {"prompt": "approve-plan"})
    (repo / "backend/app/modules/assets/service.py").write_text("x = 2\n")
    t = repo / "backend/tests/unit/test_assets_fix.py"
    t.parent.mkdir(parents=True)
    t.write_text("def test_x(): pass\n")
    r = af(repo, "review", "set", stdin=json.dumps({"verdict": "approve", "dod_met": True}))
    assert r.returncode != 0 and "repro_test" in r.stdout


def test_docs_skip_only_for_allowed_types(repo: Path) -> None:
    approve_plan(repo)
    (repo / "backend/app/modules/assets/service.py").write_text("x = 2\n")
    assert af(repo, "docs", "--skip", "nothing to document").returncode != 0


# ------------------------------------------------------------------ full commit path


def _use_fast_verify(repo: Path) -> None:
    cfg_path = repo / ".claude" / "loop.json"
    cfg = json.loads(cfg_path.read_text())
    cfg["verify_commands"] = [f'"{sys.executable}" -c "pass"']
    cfg_path.write_text(json.dumps(cfg))
    git(repo, "add", ".claude/loop.json")
    git(repo, "commit", "-q", "-m", "test: fast verify")


def test_commit_blocked_without_gates(repo: Path) -> None:
    r = run_hook(repo, "commit_gate.py", bash('git commit -m "feat(assets): x"'))
    assert r.returncode == 2 and "plan: missing" in r.stderr


def test_non_commit_commands_pass_commit_gate(repo: Path) -> None:
    assert run_hook(repo, "commit_gate.py", bash('echo "git commit"')).returncode == 0


def test_full_happy_path_then_security_path(repo: Path) -> None:
    _use_fast_verify(repo)
    approve_plan(repo)
    (repo / "backend/app/modules/assets/service.py").write_text("x = 2\n")
    t = repo / "backend/tests/unit/test_assets_service.py"
    t.parent.mkdir(parents=True)
    t.write_text("def test_x(): pass\n")
    (repo / "docs/README.md").write_text("docs updated\n")

    assert af(repo, "docs", "--touched").returncode == 0
    assert af(repo, "verify").returncode == 0
    r = af(repo, "review", "set", stdin=json.dumps({"verdict": "approve", "dod_met": True}))
    assert r.returncode == 0, r.stdout + r.stderr
    run_hook(repo, "approval_gate.py", {"prompt": "approve-ship"})
    git(repo, "add", "backend/app/modules/assets/service.py", "backend/tests/unit/test_assets_service.py", "docs/README.md")
    r = af(repo, "ship")
    assert r.returncode == 0, r.stderr

    ok = run_hook(repo, "commit_gate.py", bash('git commit -m "feat(assets): add service"'))
    assert ok.returncode == 0, ok.stderr
    bad = run_hook(repo, "commit_gate.py", bash('git commit -m "Added stuff"'))
    assert bad.returncode == 2 and "Conventional Commit" in bad.stderr
    scope = run_hook(repo, "commit_gate.py", bash('git commit -m "feat(claude): x"'))
    assert scope.returncode == 2

    # an edit after approve-ship invalidates everything bound to the diff
    (repo / "docs/README.md").write_text("changed again\n")
    stale = run_hook(repo, "commit_gate.py", bash('git commit -m "feat(assets): add service"'))
    assert stale.returncode == 2 and "stale" in stale.stderr


def test_security_path_needs_security_verdict(repo: Path) -> None:
    _use_fast_verify(repo)
    plan = {**PLAN, "scope_paths": ["backend/", "docs/"]}
    assert af(repo, "plan", "set", stdin=json.dumps(plan)).returncode == 0
    run_hook(repo, "approval_gate.py", {"prompt": "approve-plan"})
    src = repo / "backend/app/modules/organization/grants.py"
    src.parent.mkdir(parents=True)
    src.write_text("g = 1\n")
    t = repo / "backend/tests/unit/test_organization_grants.py"
    t.parent.mkdir(parents=True)
    t.write_text("def test_g(): pass\n")
    (repo / "docs/README.md").write_text("docs\nmore\n")
    af(repo, "docs", "--touched")
    af(repo, "verify")
    af(repo, "review", "set", stdin=json.dumps({"verdict": "approve", "dod_met": True}))
    status = af(repo, "status")
    assert "security: missing" in status.stdout
    af(repo, "security", "set", stdin=json.dumps({"verdict": "block", "findings": ["x"]}))
    assert "verdict is block" in af(repo, "status").stdout


def test_migration_needs_isolation_test(repo: Path) -> None:
    approve_plan(repo)
    mig = repo / "backend/migrations/versions/0002_x.py"
    mig.parent.mkdir(parents=True)
    mig.write_text("# m\n")
    assert "isolation or scope test" in af(repo, "status").stdout


# ------------------------------------------------------------------ stop hook and tracker


def test_stop_blocks_false_done(repo: Path) -> None:
    approve_plan(repo)
    (repo / "backend/app/modules/assets/service.py").write_text("x = 3\n")
    af(repo, "done")
    r = run_hook(repo, "verify_stop.py", {})
    assert json.loads(r.stdout)["decision"] == "block"
    assert run_hook(repo, "verify_stop.py", {"stop_hook_active": True}).stdout == ""


def test_tracker_picker() -> None:
    text = "\n".join(
        [
            "| M1.1-T1 | Add LICENSE | reuse lint passes | ☑ |",
            "| M1.1-T2 | Write README | README renders | ☐ |",
            "| M1.1-T3 | Write CONTRIBUTING | covers setup | ☐ |",
            "| M1.2-T1 | Backend project | CI green | ☐ |",
        ]
    )
    tasks = parse_tracker(text)
    assert [t["task_id"] for t in tasks] == ["M1.1-T1", "M1.1-T2", "M1.1-T3", "M1.2-T1"]
    assert pick_next(tasks)["task_id"] == "M1.1-T2"
    tasks[1]["status"] = "◐"
    assert pick_next(tasks)["task_id"] == "M1.1-T2"


def test_tracker_parses_part_ids_and_issue_column() -> None:
    text = "\n".join(
        [
            "| P6-01a | Worker process | #60 | Worker isolation tests pass | ☑ |",
            "| P6-01b | Job runner | #61 | Jobs stop at their time limit | ☐ |",
            "| P10-01 | Import upload | #90 | Bad files are rejected | ☐ |",
        ]
    )
    tasks = parse_tracker(text)
    assert [t["task_id"] for t in tasks] == ["P6-01a", "P6-01b", "P10-01"]
    assert [t["milestone"] for t in tasks] == ["P6", "P6", "P10"]
    assert tasks[1]["title"] == "Job runner"
    assert tasks[1]["done_when"] == "Jobs stop at their time limit"
    assert pick_next(tasks)["task_id"] == "P6-01b"
