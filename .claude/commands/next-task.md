---
description: Pick the next roadmap task, draft its plan (criteria, scope_paths, verify), freeze it with af.py plan set, and ask the human to approve
argument-hint: "[task-id to override the tracker pick, e.g. M1.2-T5]"
---

PLAN step of the AssetFlow loop. Do not edit any source file in this command.

1. Check state: `python .claude/hooks/af.py status`. If a plan for another task is open with uncommitted changes, stop and report it.
2. Get the draft:
   - no argument: `python .claude/hooks/af.py next-task`
   - argument `$ARGUMENTS`: read that row from `docs/tracker/roadmap-tracker.md` and build the same JSON shape by hand.
   If the result is `no task ready`, report it and stop. If the tracker is missing (before M1.1), ask the human for the task.
3. Create the branch before `plan set` (plan state is stored per branch; `main` is protected):
   `git switch -c <commit_type>/<issue-or-task-id>-<short-kebab-description>` (for example `feat/m1-2-t5-check-migrations`).
4. Read the task context:
   - the tracker row and its milestone heading in `docs/tracker/roadmap-tracker.md`;
   - the plan section for that task (grep the task id and its milestone in `../Plan/OpenSource.AssetFlow.md` when present,
     and in `docs/specs/`, `docs/decisions/`);
   - the §C4 pattern, §C5.4 tenancy rules and §C8 test kinds that apply.
5. Fill the draft:
   - `commit_type`: one of `feat fix docs test refactor perf chore ci build style revert`.
   - `spec_ref`: `docs/specs/<name>.md` if one exists; `adr_refs`: ADR ids that constrain it.
   - `acceptance_criteria`: keep "Done when" as `AC1` verbatim. Split it into more criteria only when it hides several checks.
     Add the implied criteria: isolation/scope tests for tenant data, contract tests for providers/channels, docs per §C7.2.
     Each criterion gets the narrowest command that proves it, for example
     `uv run pytest backend/tests/isolation/test_work_orders.py`, `make test-contract`, `make lint`, `make config-validate`,
     `make docs-check`; fall back to `make verify`.
   - `scope_paths`: path prefixes this unit may touch. Include the tests and docs it will change,
     always `docs/tracker/` (tracker row and PROGRESS.md) and `CHANGELOG.md` for user-visible changes.
     The review gate fails any changed file outside these prefixes. Never include off-limits paths
     (`.github/workflows/`, `docs/decisions/ADR-`, `LICENSE`, `CLA.md`, `NOTICE`); if the task needs them, write
     `docs/tracker/BLOCKERS.md` and stop.
   - `tests_waiver`: empty unless the task truly has no testable source (say why).
6. Do not touch the tracker here; the writer sets the row to `◐` in its first CODE pass.
   Test-naming reminder for the draft: the review gate matches source areas to tests by path
   (`modules/<area>/` -> a changed test path containing `<area>`; `channels/slack.py` -> `slack`; `workers/sla_sweeper.py` -> `sla_sweeper`).
7. Show the draft to the human as JSON plus a short table: criterion, verify command, and which of these apply:
   security paths (loop.json `security_paths`), migration, new route, new provider/channel.
8. Freeze it (write the JSON to a scratch file first to avoid shell quoting issues):
   `python .claude/hooks/af.py plan set < <scratch>/plan.json`
   It prints `approved=false`. Never set `ASSETFLOW_PLAN_AUTOPASS`.
9. Ask exactly: "Type `approve-plan` to approve this plan, or tell me what to change."
   Stop. Do not start CODE until the human has typed `approve-plan` and `af.py status` shows the plan as approved.
   To change an approved plan the human must approve again.

Plan JSON shape (fields `af.py plan set` requires: task_id, title, commit_type, acceptance_criteria[id,text,verify], scope_paths):

```json
{
  "task_id": "M1.2-T5",
  "title": "Write scripts/check-migrations.py",
  "commit_type": "feat",
  "spec_ref": "",
  "adr_refs": [],
  "acceptance_criteria": [
    {"id": "AC1", "text": "A test migration without row-level security fails", "verify": "uv run pytest backend/tests/unit/test_check_migrations.py", "done": false}
  ],
  "scope_paths": ["scripts/check-migrations.py", "backend/tests/unit/test_check_migrations.py", "Makefile", "docs/tracker/", "docs/guides/testing.md"],
  "tests_waiver": ""
}
```
