# AssetFlow Claude Code setup

This folder turns Claude Code into a gated delivery loop for AssetFlow. It enforces the plan's engineering rules (plan Part C) locally, before CI does. Humans keep the two decisions that matter: approving a plan and approving a ship.

| Path | What it is |
| --- | --- |
| `loop.json` | Single source of truth: tracker paths, verify commands, source/test/doc/security/migration patterns, protected paths, commit types |
| `hooks/` | Python hooks (run through `hooks/py`), `af.py` helper, `lib/state.py`, `lib/gates.py`, `tests/` |
| `settings.json` | Hook wiring and allow/deny permissions |
| `rules/` | Auto-loaded rules; path-scoped ones load only when matching files are touched |
| `context/` | Orientation guides per area, with plan section references |
| `references/definition-of-done.md` | §C11 checklist used by the review step |
| `agents/` | `verifier`, `security-reviewer`, `migration-reviewer`, `spec-reviewer` |
| `commands/` | `/next-task`, `/spec`, `/spec-review`, `/spec-tasks`, `/ship` |
| `skills/assetflow-loop/` | The loop procedure (writer and verifier passes) |
| `state/` | Git-ignored gate artifacts (never edit by hand) |

## The loop

```
             human: approve-plan                                      human: approve-ship
                    |                                                          |
 next-task --> PLAN --> CODE --> DOCS --> VERIFY --> REVIEW --> SECURITY --> SHIP --> commit --> PR
   ^                      ^                  |          |           |                            |
   |                      +---- LOOP_FAIL ---+-changes--+---block---+                            |
   |                           (max 3 writer iterations; 4th -> BLOCKERS.md)                      |
   +------------------------------------------- next unit <---------------------- CI green -------+
```

Docs come before verify and review because editing docs changes the diff, and every gate artifact is bound to the diff.

| Stage | Who | Command | Gate recorded |
| --- | --- | --- | --- |
| PLAN | agent, then **human** | `python .claude/hooks/af.py next-task` -> edit JSON -> `python .claude/hooks/af.py plan set < plan.json`; human types `approve-plan` | `state/plan/<branch>.json` (`approved: true`) |
| CODE | writer pass | edits inside `scope_paths`; `python .claude/hooks/af.py plan check <AC-id>` | (edit gate enforces plan + scope) |
| DOCS | writer pass | `python .claude/hooks/af.py docs --touched` or `python .claude/hooks/af.py docs --skip "<reason>"` | `state/docs/` |
| VERIFY | `verifier` agent | `python .claude/hooks/af.py verify` (runs `make verify`, `make test-isolation`; prints `LOOP_VERIFY_PASS`/`FAIL`) | `state/verify/` with exit codes |
| REVIEW | self-review vs DoD | `python .claude/hooks/af.py review set < review.json` | `state/review/` (`verdict`, `dod_met`, `tests_problems`) |
| SECURITY | `security-reviewer` (+ `migration-reviewer`) | `python .claude/hooks/af.py security set < security.json` (`pass`/`notes`/`block`) | `state/security/` |
| SHIP | **human**, then agent | human types `approve-ship`; `git add <paths>`; `python .claude/hooks/af.py ship`; `git commit -m "type(scope): subject"` | `state/ship-approval/`, `state/ship-ready/` (60 min TTL) |
| DONE | agent | `python .claude/hooks/af.py done` | `state/claimed-done/` |

`python .claude/hooks/af.py status` shows the branch, the plan and every open gate. `af.py plan show` prints the frozen plan.

### Human keywords

Type these as the **first line** of a prompt (optionally after "ok", "yes" or "please"). Negated or questioning forms are ignored.

- `approve-plan`: approves the frozen plan on the current branch. There is no agent command for this; `af.py plan approve` is refused and denied in `settings.json`.
- `approve-ship`: approves shipping the current diff (bound to `diff_sha`; any later edit makes it stale).

### Plan JSON (minimum)

```json
{"task_id": "M1.4-T3", "title": "...", "commit_type": "feat",
 "acceptance_criteria": [{"id": "AC1", "text": "...", "verify": "make test-isolation", "done": false}],
 "scope_paths": ["backend/app/modules/organization/", "backend/tests/"], "tests_waiver": ""}
```

### Review rules checked by `af.py review set`

- Source changed in an area (`assets`, `core`, `auth`, `organization`, ...) needs a changed test whose path mentions that area, unless the plan has a `tests_waiver`.
- `commit_type: fix` needs `repro_test`: a changed test that fails without the change.
- Files outside `scope_paths` are listed as problems.

## Hooks

All hooks are Python 3.10+, launched by `sh .claude/hooks/py <hook>.py` (finds a working Python on Linux, macOS and Windows Git Bash; inactive with a warning if none).

| Hook | Event | What it does |
| --- | --- | --- |
| `session_start.py` | SessionStart | Prints the loop banner, branch, plan, open gates, tails of `BLOCKERS.md` and `PROGRESS.md` |
| `approval_gate.py` | UserPromptSubmit | Records `approve-plan` / `approve-ship` typed by the human |
| `edit_gate.py` | PreToolUse Write/Edit | Source edits need an approved plan and a path inside `scope_paths`; tests and docs are always editable |
| `protected_paths.py` | PreToolUse Write/Edit | `never`: `.env*` (not `.env.example`), `.secrets/`, `.git/`; `offlimits`: workflows, ADRs, `LICENSE`, `CLA.md`, `NOTICE`; no edits on `main`; merged migrations are immutable |
| `destructive_guard.py` | PreToolUse Bash | Blocks force push, `reset --hard`, `--no-verify`, `git add -A`/`.`, `git clean -f`, merges, `rm -rf` on roots, `DROP`; blocks shell writes (`>`, `tee`, `sed -i`, `cp`/`mv`) that would dodge the edit gate |
| `commit_gate.py` | PreToolUse Bash | `git commit` passes only when `gates.check_all()` is empty for the staged diff; checks the Conventional Commit subject |
| `ship_cleanup.py` | PostToolUse Bash | After a commit lands, clears the one-shot artifacts (the plan stays for multi-commit tasks) |
| `verify_stop.py` | Stop | After `af.py done`, refuses to end the session while source or test changes are uncommitted |
| `post_edit_lint.py` | PostToolUse Write/Edit | `ruff check` on edited Python, domain-terms check, migration reminder; findings go back to the agent |

### What the commit gate checks (`hooks/lib/gates.py`)

Approved plan; non-empty diff; verify passed on this diff; review `approve` with `dod_met: true` and no tests problems; security verdict (not `block`) when any `security_paths` file changed; an isolation or scope test changed when a migration changed; docs recorded; human `approve-ship`; fresh `ship-ready` matching the staged tree and HEAD; no unstaged changes.

## State

- `.claude/state/<kind>/<branch-slug>.json` for `plan`, `verify`, `review`, `security`, `docs`, `ship-approval`, `ship-ready`, `claimed-done`.
- Every artifact except the plan is bound to `diff_sha` = sha256 of `git diff HEAD --binary` plus the path and bytes of each untracked file. Any edit after recording makes it **stale**; re-run the step.
- Writes use a lock file and atomic replace, so two sessions on one branch do not collide.
- The folder is git-ignored and write-denied to the agent in `settings.json`.

## Bypass flags (human-only)

| Flag | Effect |
| --- | --- |
| `ASSETFLOW_GATE=off` | Disables the edit gate, the commit gate and the Bash-write rule (destructive rules have no bypass) |
| `ASSETFLOW_OFFLIMITS=ack` | Allows edits to off-limits paths while set (each edit logged) |
| `ASSETFLOW_PLAN_AUTOPASS=1` | `af.py plan set` records the plan as approved |
| `ASSETFLOW_SHIP_AUTOPASS=1` | The commit gate skips the `approve-ship` check |

Every use is appended to `.claude/state/bypass.log` (time, branch, flag, detail). The agent never sets them unless the human asks in the same session. `never` paths have no bypass.

## Better than the OpenWind setup

- **Task picker** reads `docs/tracker/roadmap-tracker.md` and drafts the plan from the row's "Done when" (resumes `◐` first; respects order within a milestone).
- **Verify is re-run and bound to the diff**, not claimed: exit codes are stored with `diff_sha`, and the verifier runs in a fresh context.
- **Security review is mandatory by path** (`security_paths` mirrors §C5.8), not by judgment.
- **Tests must be in the same area** as the source change, and a `fix` needs a reproduction test.
- **Blocking migration rule**: a migration without an isolation or scope test change cannot be committed; merged migrations cannot be edited.
- **Bash write guard**: shell redirects and `sed -i` cannot sidestep the edit gate.
- **Python hooks**, cross-platform through one launcher, with unit tests.
- **Four agents with pinned models**: `security-reviewer` (opus), `verifier`, `migration-reviewer`, `spec-reviewer` (sonnet).
- **Docs skip limited by commit type**: only `test`, `refactor`, `chore`, `ci`, `build`, `style`.

## Known limits

The hooks are a **seatbelt, not the gate**. They run only inside Claude Code, can be bypassed by a human, and trust the local git state. The real gates are on GitHub:

- `ci-complete` (aggregate of quality, tests, tenant isolation, migrations, contract, frontend, security, docker);
- the CLA check (`cla.yml`);
- contribution checks (`contribution-checks.yml`: tests changed, isolation changed, forbidden files, ADR/issue links, PR size, template);
- a `claude-hooks` CI job that runs the hook unit tests;
- CODEOWNERS: the second reviewer approves every security-path change; the maintainer merges.

## Running the hook tests

```
python -m pytest .claude/hooks/tests
```

Run them after any change to `hooks/`, `loop.json` or `settings.json`.

## Tracker format

`af.py next-task` parses rows in `docs/tracker/roadmap-tracker.md` shaped exactly like:

```
| M1.1-T1 | Task | Done when | ☐ |
```

Status marks: `☐` not started, `◐` in progress, `☑` done, `⛔` blocked. The first text cell is the title, the second is "Done when" (becomes `AC1`). Blockers go to `docs/tracker/BLOCKERS.md`; progress notes to `docs/tracker/PROGRESS.md`.
