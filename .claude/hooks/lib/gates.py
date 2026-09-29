"""Gate checks shared by the commit gate, `af.py status` and the tests.

Order of the loop (each artifact is bound to the diff it saw):
  plan (human approve-plan) -> code -> docs -> verify -> review -> security
  -> ship-approval (human approve-ship) -> ship-ready -> git commit
Docs come before verify/review because editing docs changes the diff.
"""

from __future__ import annotations

from typing import Any

from . import state as s


def tests_problems(files: list[str], plan: dict[str, Any], repro_test: str | None) -> list[str]:
    """Tests must accompany module code, and a fix needs a reproduction test."""
    problems: list[str] = []
    tests = [f for f in files if s.is_test(f)]
    keys = sorted({k for f in files if s.is_source(f) and (k := s.module_key(f))})
    waiver = (plan.get("tests_waiver") or "").strip()
    if keys and not waiver:
        if not tests:
            problems.append(f"source changed in {', '.join(keys)} but no test changed")
        else:
            missing = [k for k in keys if not any(k in t for t in tests)]
            if missing:
                problems.append(
                    "no changed test mentions area(s) " + ", ".join(missing)
                    + " (name the test after the area, or set tests_waiver in the plan)"
                )
    if plan.get("commit_type") == "fix":
        if not repro_test:
            problems.append("fix: requires repro_test (a test that fails without the change)")
        elif repro_test not in tests:
            problems.append(f"repro_test {repro_test} is not among the changed tests")
    return problems


def security_required(files: list[str]) -> list[str]:
    return [f for f in files if s.is_security_path(f)]


def migration_problems(files: list[str], plan: dict[str, Any] | None = None) -> list[str]:
    """A migration needs an isolation/scope test, unless the plan records isolation_waiver
    (the loop's form of the PR token [skip-isolation-check], e.g. an index-only migration)."""
    if any(s.is_migration(f) for f in files) and not any(s.is_isolation_test(f) for f in files):
        if (plan or {}).get("isolation_waiver", "").strip():
            return []
        return ["a migration changed but no isolation or scope test changed (§B10, §C4.8); "
                "for an index-only migration set isolation_waiver in the plan"]
    return []


def _bound(kind: str, current: str) -> tuple[dict[str, Any] | None, str | None]:
    rec = s.read_state(kind)
    if rec is None:
        return None, f"{kind}: missing"
    if rec.get("diff_sha") != current:
        return rec, f"{kind}: stale (the diff changed after it was recorded)"
    return rec, None


def check_all(for_commit: bool = True) -> list[str]:
    """Return every unmet gate. Empty list means the commit may proceed."""
    problems: list[str] = []
    files = s.changed_files()
    current = s.diff_sha()

    plan = s.read_state("plan")
    if not plan:
        problems.append("plan: missing (run /next-task or af.py plan set)")
    elif not plan.get("approved"):
        problems.append("plan: not approved (the human types approve-plan)")

    if not files:
        problems.append("diff: nothing changed against HEAD")

    verify, err = _bound("verify", current)
    if err:
        problems.append(err)
    elif not verify.get("passed"):
        failed = [c for c, code in verify.get("results", {}).items() if code != 0]
        problems.append("verify: failed: " + ", ".join(failed))

    review, err = _bound("review", current)
    if err:
        problems.append(err)
    else:
        if review.get("verdict") != "approve":
            problems.append(f"review: verdict is {review.get('verdict')!r}, needs 'approve'")
        if review.get("dod_met") is not True:
            problems.append("review: definition of done not met: " + ", ".join(review.get("dod_unmet", [])))
        problems += ["review: " + p for p in review.get("tests_problems", [])]

    sec_files = security_required(files)
    if sec_files:
        sec, err = _bound("security", current)
        if err:
            problems.append(f"{err} (security paths touched: {', '.join(sec_files[:5])})")
        elif sec.get("verdict") == "block":
            problems.append("security: security-reviewer verdict is block")

    problems += migration_problems(files, plan)

    _, err = _bound("docs", current)
    if err:
        problems.append(err)

    if for_commit:
        if s.flag("ASSETFLOW_SHIP_AUTOPASS"):
            s.log_bypass("ASSETFLOW_SHIP_AUTOPASS", current[:12])
        else:
            _, err = _bound("ship-approval", current)
            if err:
                problems.append(err + " (the human types approve-ship)")

        ready = s.read_state("ship-ready")
        if ready is None:
            problems.append("ship-ready: missing (run af.py ship after staging)")
        else:
            if ready.get("staged_tree_sha") != s.staged_tree_sha():
                problems.append("ship-ready: staged files changed after af.py ship")
            if ready.get("head") != s.head_sha():
                problems.append("ship-ready: HEAD moved after af.py ship")
            if s.age_minutes(ready["timestamp_iso"]) > s.config()["ship_ttl_minutes"]:
                problems.append("ship-ready: expired, run af.py ship again")
        if s.unstaged_files():
            problems.append("unstaged changes present: stage them explicitly or discard them")
    return problems
