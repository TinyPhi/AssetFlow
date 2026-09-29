---
name: assetflow-loop
description: The AssetFlow delivery loop (PLAN -> CODE -> DOCS -> VERIFY -> REVIEW -> SECURITY -> SHIP) with Writer/Verifier passes and af.py gates. Use for "next task", "work on M1.x-Tn", "implement", "continue the roadmap", "run the loop", "ship this", or any change to AssetFlow source.
---

# AssetFlow delivery loop

All gate state lives in `.claude/state/` and is bound to `diff_sha` (hash of `git diff HEAD` plus untracked files).
Any edit after a gate is recorded makes that gate stale. `python .claude/hooks/af.py status` lists every open gate.
Config: `.claude/loop.json` (verify commands, security paths, off-limits paths, commit types).

## Order

1. **PLAN** — `/next-task` (or `/spec-tasks`): `af.py next-task` -> fill criteria, `scope_paths`, verify commands ->
   `af.py plan set < plan.json`. The HUMAN types `approve-plan`. There is no agent command to approve.
   The edit gate blocks source edits until the plan is approved.
2. **CODE** — one unit of work, only inside `scope_paths` (Writer pass, below).
3. **DOCS** — `af.py docs --touched` if any doc changed (tracker/PROGRESS.md count), or
   `af.py docs --skip "<reason>"` only for commit types `test refactor chore ci build style`.
   Docs come BEFORE verify/review because editing docs changes the diff.
4. **VERIFY** — the verifier agent runs `af.py verify` (`make verify`, `make test-isolation`; exit codes bound to the diff).
5. **REVIEW** — `/review`, or self-review against `.claude/references/definition-of-done.md` (§C11), then
   `af.py review set < review.json`:
   `{"verdict":"approve|changes","dod_met":true,"dod_unmet":[],"findings_triaged":{"accepted":[],"deferred":[],"rejected":[]},"repro_test":"backend/tests/..."}`
   `repro_test` is required when `commit_type` is `fix` (a test that fails without the change).
   The command also fails on files outside `scope_paths` and on source areas with no matching test.
6. **SECURITY** — if the diff touches any loop.json `security_paths`: invoke the `security-reviewer` agent, then
   `af.py security set < security.json` with `{"verdict":"pass|notes|block","findings":[...]}`.
   If a migration changed, also invoke `migration-reviewer` and fix its CHANGES REQUIRED items first.
7. **SHIP** — `/ship`: human types `approve-ship`; `git add <exact paths>` (never `-A`); `af.py ship`;
   `git commit -m "<type>(<scope>): <subject>"`; push the branch; open a PR with the acceptance criteria in the body;
   watch CI; NEVER merge.

`af.py plan check <AC-id>` marks a criterion done once its verify command passed. `af.py done` claims the unit done;
the Stop hook then refuses to end the session while source changes are uncommitted.

## Writer pass (main session or a writer subagent)

- Set the tracker row in `docs/tracker/roadmap-tracker.md` to `◐` on the first pass.
- Implement one unit: the smallest change that satisfies the next unmet criterion, test first where practical.
  Follow the scaffold skills: `new-module`, `new-route`, `new-migration`, `new-provider`, `new-channel`.
- Every new file starts with the SPDX header in its comment style:
  `SPDX-FileCopyrightText: <year> TinyPhi` / `SPDX-License-Identifier: AGPL-3.0-only`.
- Update required docs (§C7.2) and append to `docs/tracker/PROGRESS.md`:
  `- <date> <task_id> iter <n>: <what changed>; next: <next criterion or "verify">`.
- When the writer believes every criterion is met, set the tracker row to `☑` in the same diff.
- Record docs: `af.py docs --touched` (or `--skip` where allowed).
- Never run `af.py verify`, `af.py review set`, `af.py ship`, `git add` or `git commit` in a writer pass.

## Verifier pass (fresh context)

Invoke the `verifier` agent. It reads the plan and the diff, runs `af.py verify` itself, runs each criterion's command,
ignores the writer's narrative, and ends with exactly one of:

- `LOOP_DONE` -> run `af.py plan check <AC-id>` for each proven criterion, then REVIEW, SECURITY, SHIP.
- `LOOP_FAIL` -> next writer pass with the verifier's fix list. Maximum 3 writer iterations per unit; the 4th is BLOCKED.
- `LOOP_BLOCKED` -> write the blocker to `docs/tracker/BLOCKERS.md` and stop.

If REVIEW returns `changes` or SECURITY returns `block`, go back to CODE (counts as an iteration); every later step re-runs.

## Stop and write BLOCKERS.md when

- a schema or API contract change is needed that the plan does not contain;
- a criterion is ambiguous (two readings give different code);
- the same test fails after 2 fix attempts;
- security-reviewer verdict is `block` and the fix is outside scope or needs a design decision;
- the work needs an off-limits path: `.github/workflows/`, `docs/decisions/ADR-*`, `LICENSE`, `CLA.md`, `NOTICE`.

Entry format in `docs/tracker/BLOCKERS.md`:

```
## <date> <task_id> <short title>
- blocker: <exact failing command / question / path>
- evidence: <output excerpt, file:line>
- tried: <attempts>
- needs: <decision or action from the lead engineer>
```

Set the tracker row to `⛔` and stop the session (commit nothing).

## Exit conditions (unit complete)

1. Every acceptance criterion is checked (`af.py plan show` shows `done: true`).
2. `af.py verify` passed on the final diff (`LOOP_VERIFY_PASS`).
3. The tracker row is `☑` in the committed diff.
4. The PR is open and CI is green (`gh pr checks`). Merging is the maintainer's decision.

## Bypass flags (human-only)

`ASSETFLOW_GATE=off`, `ASSETFLOW_OFFLIMITS=ack`, `ASSETFLOW_PLAN_AUTOPASS=1`, `ASSETFLOW_SHIP_AUTOPASS=1`
are logged to `.claude/state/bypass.log`. Never set them unless the human asks in this session.

## Commit rules

Conventional Commits with a scope from §B12.3 (`core organization assets maintenance notifications audit workflow-engine
automation-engine provider-<name> channel-<name> worker web config deploy docs ci`); scope `claude` is forbidden.
Types from loop.json `commit_types`. No `Signed-off-by` (CLA, no DCO). Branch `<type>/<issue>-<short-kebab>`; never commit to `main`.
