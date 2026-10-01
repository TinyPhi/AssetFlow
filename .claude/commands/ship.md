---
description: Walk the SHIP step - approve-ship gate, exact staging, af.py ship, Conventional Commit, push, PR, watch CI (never merge)
argument-hint: "[optional PR title override]"
---

SHIP step of the AssetFlow loop. At every failure: stop, run `python .claude/hooks/af.py status`, show its output verbatim,
and say which step failed. Never use a bypass flag (`ASSETFLOW_GATE=off`, `ASSETFLOW_OFFLIMITS=ack`,
`ASSETFLOW_PLAN_AUTOPASS=1`, `ASSETFLOW_SHIP_AUTOPASS=1`) unless the human explicitly asks; each use is logged
to `.claude/state/bypass.log`.

1. **Pre-check.** `python .claude/hooks/af.py status`. The only open gates allowed now are `ship-approval` and `ship-ready`.
   Anything else (plan, verify, review, security, docs, migration test) means go back to that step; stop.
2. **Human gate.** Show the summary: task id, criteria with done state (`af.py plan show`), changed files
   (`git status --porcelain`), security verdict if any. Ask: "Type `approve-ship` to ship this diff."
   Wait. The approval is bound to the current diff; any edit after it needs a new `approve-ship`.
3. **Stage exact paths.** `git add <path> <path> ...` listing every changed file from `git status --porcelain`
   that belongs to the plan. Never `git add -A`, `git add .` or `git commit -a`.
   Never stage `.env*` (except `.env.example`), `.secrets/`, `.claude/state/`.
   Check: `git diff --cached --name-only` equals the intended list and `git diff --name-only` is empty.
4. **Record ship-ready.** `python .claude/hooks/af.py ship`. It fails on unstaged changes, untracked source/test files,
   or any unmet gate. Valid for 60 minutes and only for this staged tree and HEAD.
5. **Commit.** One Conventional Commit, scope required:
   `git commit -m "<type>(<scope>): <summary>"`
   - `<type>` = the plan's `commit_type`; summary imperative, lowercase, no period, <= 72 chars, US English.
   - `<scope>` from §B12.3: `core organization assets maintenance notifications audit workflow-engine automation-engine
     provider-<name> channel-<name> worker web config deploy docs ci`. Scope `claude` is forbidden.
   - Body only when the why is not obvious (wrap at 100). Footer `Refs: #<issue>`; `BREAKING CHANGE:` when applicable.
   - No `Signed-off-by` (AssetFlow uses a CLA, not DCO). A `Co-Authored-By:` trailer is allowed.
   If the commit hook refuses, show its message and `af.py status`; fix the cause, never `--no-verify`.
6. **Claim done.** `python .claude/hooks/af.py done`.
7. **Push.** `git push -u origin <branch>`. Never push to `main`; never force-push a shared branch.
8. **Open the PR** (draft first, §C3.4):
   `gh pr create --draft --base main --title "<commit subject>" --body-file <scratch>/pr.md`
   Body: fill `.github/pull_request_template.md` if present, and always include:
   - task id, spec and ADR links; `Closes #<issue>`;
   - `## Acceptance criteria` as a checklist, each with the verify command and result;
   - `## Security notes`: security paths touched, security-reviewer verdict and accepted/deferred findings,
     migration-reviewer verdict;
   - `## Tests`: which suites were added (unit, integration, isolation, scope, contract, E2E);
   - `## Docs`: docs touched or the skip reason; dependency justification (§C4.11) if any.
9. **Watch CI.** `gh pr checks --watch`. On failure, read the failing job log (`gh run view <id> --log-failed`),
   report it, and start a new loop iteration on the same branch (CODE -> DOCS -> VERIFY -> REVIEW -> SECURITY -> SHIP).
   When green: `gh pr ready`. The tracker row must already be `☑` in this commit (the writer sets it before DOCS,
   because any later edit invalidates verify/review); if it is not, that is a new loop iteration, not a silent edit.
10. **Never merge.** Do not run `gh pr merge`, do not approve your own PR, do not change branch protection.
    Report the PR URL and CI status to the human; merging is the maintainer's decision.
