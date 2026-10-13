# Mistake_Traces.md

Every trace of a mistake, one occurrence each, linked to its kind in
[Mistake_Learn.md](Mistake_Learn.md). Not loaded automatically: open it when a kind points here,
when `find` names a kind, or when you review how the agent behaves (`report`).

Each trace records **where** it happened, the **trigger** (what the agent was doing), the **root
cause**, the **fix**, what **verified** the fix and that nothing else broke (the full exit check),
and an optional reviewer **comment**. `pending` is allowed for fix and verified; `report` lists
every open one. Traces are append-only; ids are never reused.

Commands: `python scripts/check-mistakes-log.py find | new | seen | retire | report | sync | archive`
(details in the script's docstring).

## Retired kinds

| ID | Status | Area | Rule | Learning: why it happens | Check | Enforced by | Traces |
| --- | --- | --- | --- | --- | --- | --- | --- |
| M-007 | dormant | auth | Identity comes only from `AuthMiddleware`, never from request headers; tests use `dependency_overrides` | Tests need an identity without a real sign-in; the shortcut lands in application code and, with no environment gate, becomes an anonymous admin backdoor. Later fixes copy the existing pattern. | review new auth code for header-derived identity | - | [T-20261007-76e7](#t-20261007-76e7), [T-20261007-7cbc](#t-20261007-7cbc) |

## Traces

### <a id="t-20261007-0669"></a>T-20261007-0669 · 2026-10-07 · [M-008](Mistake_Learn.md#m-008)

- **Where:** backend/app/api/auth.py (audit NEW-1, from PR #223)
- **Trigger:** building the BFF session cookie
- **Root cause:** a dev default key kept as fallback, read from a config field that did not exist
- **Fix:** key from session_cookie_key, boot refuses without it (37c283a)
- **Verified by:** test_config guards; full exit check green

### <a id="t-20261007-73b7"></a>T-20261007-73b7 · 2026-10-07 · [M-010](Mistake_Learn.md#m-010)

- **Where:** backend/tests/isolation/pg_harness.py
- **Trigger:** running isolation tests without a shared database
- **Root cause:** throwaway container started with no name, label or --rm; killed runs left 13 behind
- **Fix:** named, labelled, --rm, atexit cleanup, reuses af-postgres (2029fa5)
- **Verified by:** no unlabelled containers after a full run

### <a id="t-20261007-76e7"></a>T-20261007-76e7 · 2026-10-07 · [M-007](#retired-kinds)

- **Where:** api/v1 routes, core/request_member.py (audit NEW-5)
- **Trigger:** making route tests pass without a real session
- **Root cause:** a test shortcut was placed in application code with no environment gate
- **Fix:** all header fallbacks deleted (b8376a4)
- **Verified by:** authz_matrix test_no_header_identity; full exit check green

### <a id="t-20261007-7cbc"></a>T-20261007-7cbc · 2026-10-07 · [M-007](#retired-kinds)

- **Where:** group C commit 09b969b
- **Trigger:** fixing team-scope escalation (AF-006)
- **Root cause:** extended the same header shim with x-scope-id instead of using a fixture
- **Fix:** edits reverted (9db6ca7); tests use tests/support/header_identity.py
- **Verified by:** scope tests pass; check-no-header-identity runs in make lint

### <a id="t-20261007-b21a"></a>T-20261007-b21a · 2026-10-07 · [M-006](Mistake_Learn.md#m-006)

- **Where:** commit dd4a85d, providers/secrets/file.py (audit NEW-4)
- **Trigger:** fixing a CodeQL clear-text-logging alert
- **Root cause:** did not know LogRecord reserves those attribute names
- **Fix:** keys renamed (group B, 91b4bb4)
- **Verified by:** test_reading_an_unset_credential_fails passes; full exit check green

### <a id="t-20261007-db59"></a>T-20261007-db59 · 2026-10-07 · [M-009](Mistake_Learn.md#m-009)

- **Where:** backend/app/api/auth.py exchange_session (audit NEW-2)
- **Trigger:** supporting opaque mock tokens in sign-in
- **Root cause:** turned a failed token check into principal=None and continued
- **Fix:** fail closed (5923d05); mock tokens made verifiable (c0cd5ee)
- **Verified by:** e2e test_mock_sign_in; full exit check green

### <a id="t-20261007-e6b0"></a>T-20261007-e6b0 · 2026-10-07 · [M-002](Mistake_Learn.md#m-002)

- **Where:** integ/regroup-final, telemetry scrubber test
- **Trigger:** writing a test sample for the log scrubber
- **Root cause:** copied a realistic provider-shaped example key
- **Fix:** test line rewritten so it is no longer key-shaped
- **Verified by:** gitleaks clean over the new commits

### <a id="t-20261007-ec13"></a>T-20261007-ec13 · 2026-10-07 · [M-013](Mistake_Learn.md#m-013)

- **Where:** 7b6f94a, dd4a85d, 7599912
- **Trigger:** fixing CI alerts on old stacked PRs
- **Root cause:** committed on a mid-stack branch; the top branch never received them
- **Fix:** cherry-picked into integ/regroup-final
- **Verified by:** present in regroup/12; full exit check green

### <a id="t-20261008-3b32"></a>T-20261008-3b32 · 2026-10-08 · [M-003](Mistake_Learn.md#m-003)

- **Where:** #294 scripts/dev_setup.py:393
- **Trigger:** running migrations from the dev setup job
- **Root cause:** wrote a DSN with the password to /tmp to pass it to alembic
- **Fix:** pending: read the DSN from OpenBao via secret://
- **Verified by:** pending

### <a id="t-20261008-48b7"></a>T-20261008-48b7 · 2026-10-08 · [M-001](Mistake_Learn.md#m-001)

- **Where:** regroup PR 9 (branch regroup/09)
- **Trigger:** splitting the integration branch into stacked PRs
- **Root cause:** used the generic Conventional Commits type list instead of the repo config
- **Fix:** branches rebuilt; commit reworded to chore
- **Verified by:** commitlint 0 problems over 22 commits

### <a id="t-20261008-5a73"></a>T-20261008-5a73 · 2026-10-08 · [M-005](Mistake_Learn.md#m-005)

- **Where:** #291 backend/app/providers/secrets/file.py:121
- **Trigger:** fixing NEW-4 (reserved log key)
- **Root cause:** renamed name to key_name, a name CodeQL taints
- **Fix:** pending
- **Verified by:** pending

### <a id="t-20261008-75f3"></a>T-20261008-75f3 · 2026-10-08 · [M-012](Mistake_Learn.md#m-012)

- **Where:** audit fix report (step 1)
- **Trigger:** finishing a long task
- **Root cause:** skipped suites after a small last commit and reported green
- **Fix:** full exit check re-run on the final tip
- **Verified by:** owner review accepted the re-run counts

### <a id="t-20261008-b4d0"></a>T-20261008-b4d0 · 2026-10-08 · [M-011](Mistake_Learn.md#m-011)

- **Where:** regroup PRs 5 and 10
- **Trigger:** splitting code by layer into stacked PRs
- **Root cause:** production code imported a module that only a later PR adds
- **Fix:** merged PRs 5 and 6; routes.tsx split between PRs 9 and 10
- **Verified by:** each branch green alone (split report)

### <a id="t-20261008-ba11"></a>T-20261008-ba11 · 2026-10-08 · [M-012](Mistake_Learn.md#m-012)

- **Where:** regroup split report
- **Trigger:** reporting the 13 branches
- **Root cause:** claimed commitlint clean without running it on every commit
- **Fix:** commitlint run over the whole chain
- **Verified by:** commitlint 0 problems over 22 commits

### <a id="t-20261008-bad3"></a>T-20261008-bad3 · 2026-10-08 · [M-004](Mistake_Learn.md#m-004)

- **Where:** #291, #294 (file.py, dev_setup.py)
- **Trigger:** making CodeQL go green
- **Root cause:** treated the alert as noise instead of a real leak; current CodeQL ignores lgtm comments anyway
- **Fix:** pending
- **Verified by:** pending

### <a id="t-20261008-e905"></a>T-20261008-e905 · 2026-10-08 · [M-003](Mistake_Learn.md#m-003)

- **Where:** #294 scripts/dev_setup.py:448
- **Trigger:** finishing make dev so the owner can sign in
- **Root cause:** convenience: showed the admin password at the end of setup
- **Fix:** pending
- **Verified by:** pending

### <a id="t-20261009-93c2"></a>T-20261009-93c2 · 2026-10-09 · [M-001](Mistake_Learn.md#m-001)

- **Where:** docs/mistakes-log commit 55fbc21
- **Trigger:** committing the two-file mistake log
- **Root cause:** put file names in their real case in the subject; commitlint requires a lower-case subject
- **Fix:** subject reworded and commit amended (unpushed)
- **Verified by:** commitlint 0 problems over the 5 branch commits
- **Comment:** same kind as T-20261008-48b7: knowledge of the config was not applied before committing
