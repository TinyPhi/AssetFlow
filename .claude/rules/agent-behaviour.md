# Agent behaviour

Always loaded. How an AI agent works in this repository. The human is the lead engineer (maintainer); the agent executes.

## Autonomy level

- Execute an **approved** plan end to end without asking for confirmation at each step.
- Surface, do not decide: architecture, security, tenancy, public API/event/config contracts, provider or channel interfaces, engine rule types. These need an ADR or spec (plan §B12.1, §B12.2).
- The plan document is the source of truth: `../Plan/OpenSource.AssetFlow.md` until it moves into `docs/`. Settled decisions are in §B3 (D1–D18) and §B17. Never contradict them in code.

## Startup (every session, in this order)

1. Read `CLAUDE.md`.
2. Read `docs/tracker/PROGRESS.md` and `docs/tracker/BLOCKERS.md` (if they exist).
3. Run `python .claude/hooks/af.py status` to see the branch, the plan and every open gate.
4. Run `git status` and `git log --oneline -5`.
5. If a plan is in progress on this branch, resume it. Otherwise run `python .claude/hooks/af.py next-task`.

## One unit of work per iteration

- One tracker task (`M1.4-T3`) = one branch = one plan = one commit series = one PR.
- Do not start a second task until the current one is committed, or written to `BLOCKERS.md`.
- Keep the diff inside the plan's `scope_paths`. Out-of-scope edits make the review gate fail.
- At the end of the unit, append a short entry to `docs/tracker/PROGRESS.md` (task id, what changed, evidence, next step).

## Proceed autonomously

- Reading any file, running tests, linters, `make verify`, `make test-isolation`, `af.py status`.
- Writing code, tests and docs inside the approved `scope_paths`.
- Fixing lint, type and test failures caused by your own change.
- Adding tests that the Definition of Done requires (`.claude/references/definition-of-done.md`).
- Recording gate artifacts: `af.py verify`, `af.py review set`, `af.py security set`, `af.py docs`, `af.py ship`.
- Creating a feature branch or a worktree for the current task.

## Stop and write `docs/tracker/BLOCKERS.md`

Write one entry (task id, what blocks, what you tried, the decision needed, options) and stop the unit when:

- A **contract change is not in the plan**: API shape, event payload, config schema, provider/channel interface, database-wide change.
- An **acceptance criterion is ambiguous** or conflicts with the plan document.
- The **same test fails after 2 fix attempts**. Do not try a third blind variation.
- The **security reviewer returns `block`**.
- The work needs an **off-limits path** (`.github/workflows/`, `docs/decisions/ADR-*`, `LICENSE`, `CLA.md`, `NOTICE`).
- **Config-first check fails**: the behaviour is specific to one industry or organization. It belongs in `config/domains/*.yaml` (statuses, workflows, priorities, SLAs, automations, vocabulary), not in code (§B12.2, D8, D12). If the engine cannot express it, that is an engine change and needs an ADR.
- A required secret, credential or external account is missing.

## Never

- Merge a PR, push to `main`, or approve your own plan or ship. Only the human types `approve-plan` and `approve-ship`.
- `git push --force`, `git reset --hard` on shared history, `git commit --no-verify`, `git add -A` / `git add .`.
- Edit `.env`, `.env.*` (except `.env.example`), or anything in `.secrets/`.
- Write credentials, tokens or keys anywhere except OpenBao (in production) or generated, git-ignored local secret files. Never in code, tests, fixtures, comments, docs or commit messages.
- Set a bypass flag (`ASSETFLOW_GATE=off`, `ASSETFLOW_OFFLIMITS=ack`, `ASSETFLOW_PLAN_AUTOPASS=1`, `ASSETFLOW_SHIP_AUTOPASS=1`) unless the human asked for it in this session.
- Edit ADRs, workflows, `LICENSE`, `CLA.md` or `NOTICE`.
- Put industry, company or product-specific terms in `backend/app/` or `frontend/src/` (§C1.2, §C12 denylist).
- Mock the database, skip the isolation suite, or weaken a test to make it pass.

## Skill chain (the loop)

```
next-task -> plan set -> [human: approve-plan] -> code + tests -> docs
  -> verify -> review -> security (if security paths) -> [human: approve-ship]
  -> git add <paths> -> ship -> git commit -> done
```

| Stage    | Driver                                  | Command                                                              |
| -------- | --------------------------------------- | -------------------------------------------------------------------- |
| Spec     | `/spec`, `/spec-review` (spec-reviewer), `/spec-tasks` | non-trivial features only; spec in `docs/specs/`          |
| Plan     | `/next-task`                            | `af.py next-task`, `af.py plan set < plan.json`; wait for `approve-plan` |
| Code     | writer pass (skill `assetflow-loop`)    | edit inside `scope_paths`; tests in the same area                    |
| Docs     | writer pass                             | `af.py docs --touched` or `--skip "<reason>"` (test/refactor/chore/ci/build/style only) |
| Verify   | `verifier` agent (fresh context)        | `af.py verify`; ends `LOOP_DONE`, `LOOP_FAIL` or `LOOP_BLOCKED`; then `af.py plan check <AC-id>` |
| Review   | self-review against the DoD             | `af.py review set < review.json`                                     |
| Security | `security-reviewer` (+ `migration-reviewer` for migrations) | `af.py security set < security.json`             |
| Ship     | `/ship`                                 | wait for `approve-ship`; `git add <paths>`; `af.py ship`; `git commit`; push; PR; never merge |
| Done     | —                                       | `af.py done`                                                         |

At most 3 writer iterations per unit; the 4th is a blocker. Details: `.claude/README.md` and `.claude/skills/assetflow-loop/SKILL.md`.
