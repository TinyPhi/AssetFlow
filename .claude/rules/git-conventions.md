# Git conventions

Always loaded. Source: plan §B12.3, §C6.2, §C6.4, §C9.7, §C12 (commitlint).

## Branches

- Format: `<type>/<task-id>-<short-kebab-desc>`, for example `feat/M1.4-T3-provisioning`, `fix/M2.2-T5-custody-ack`.
- When the work comes from a GitHub issue instead of a tracker task: `<type>/<issue>-<short-desc>` (`feat/142-floating-schedules`).
- Never commit to `main`. `main` is protected and always releasable.
- Worktrees for parallel work: `git worktree add ../assetflow-<type>-<task> -b <branch>`, for example `../assetflow-feat-M1.4-T3`. Remove with `git worktree remove` when the PR is merged.

## Commits (Conventional Commits)

Format: `type(scope): subject`

- Subject: imperative, lowercase, no trailing period, header at most 72 characters.
- Body: optional; explain *why*; wrap at 100 characters.
- Breaking change: `type(scope)!: subject` plus a `BREAKING CHANGE:` footer.
- Optional footer `Refs: #N`.
- **No `Signed-off-by` line.** The CLA (`CLA.md`) covers contributions; there is no DCO.
- An AI assistant may add a `Co-Authored-By:` line. The human author remains responsible.

**Types** (`.claude/loop.json` `commit_types`): `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `chore`, `ci`, `build`, `style`, `revert`.

**Scopes** (§B12.3): `core`, `organization`, `assets`, `maintenance`, `notifications`, `audit`, `workflow-engine`, `automation-engine`, `provider-<name>` (`provider-oidc`, `provider-openbao`, `provider-file`, `provider-otel`, `provider-postgres`), `channel-<name>` (`channel-inapp`, `channel-email`, `channel-webhook`), `worker`, `web`, `config`, `deploy`, `docs`, `ci`.

- The scope `claude` is forbidden. Changes to `.claude/` use `chore(ci)` or `docs(docs)` as fits.
- A new provider or channel adds its scope to `commitlint.config.cjs` in the same PR.

Examples:

```
feat(maintenance): add floating schedule mode
fix(assets): reject custody transfer to a suspended member
test(organization): cover scope leakage for sibling org units
```

## Staging

- Stage explicit paths only: `git add backend/app/modules/assets/service.py backend/tests/...`.
- Never `git add -A`, `git add .` or `git commit -a`. The commit gate refuses unstaged or untracked source/test files.
- Never stage `.env`, `.secrets/`, `*.pem`, `*.key`, `*.p12`, database dumps or `node_modules` (contribution checks fail on them).
- Never `--no-verify`. If a pre-commit hook fails, fix the cause.

## Pull requests

Open as a **draft**; mark ready only when every box is honest. One concern per PR; target under 400 changed lines (hard check at 800, excluding lock files, fixtures and generated docs). Link the issue (`Closes #N`).

Template (`.github/pull_request_template.md`, §B12.7):

1. **Summary:** what and why; `Closes #N`.
2. **Type:** bug fix, feature, provider, notification channel, domain config, docs, refactor, security.
3. **Checklist:**
   - [ ] tests added or updated; coverage does not drop
   - [ ] new tables: `organization_id`, RLS with `FORCE`, index, isolation tests; views `security_invoker`
   - [ ] new routes declare a permission and a rate limit
   - [ ] new events and config keys documented
   - [ ] migrations include a downgrade
   - [ ] no industry, company or product-specific terms in code
   - [ ] no secrets, tokens or personal data in code, tests, fixtures or logs
   - [ ] docs and CHANGELOG updated
   - [ ] ADR or spec linked if architectural or non-trivial
   - [ ] CLA accepted by the author
4. **Security notes:** tenancy and scope impact, new inputs, new outbound calls, or "none". On security paths: "self-reviewed against §C5.9".
5. **How to verify:** exact commands and steps.

## Review and merge

- The agent **never merges**. A maintainer squash-merges with a Conventional Commit title; the branch is deleted.
- No force-push during review; push new commits so reviewers see what changed.
- Security paths (§C5.8) need the **second reviewer's** approval through CODEOWNERS (`@TinyPhi/assetflow-security`), from Phase 1 on. The single-maintainer exception does not cover them.
- Required checks on `main`: `ci-complete`, the CLA check, and contribution checks.
