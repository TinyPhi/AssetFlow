# Progress Log

Record of completed tasks, tools, and milestone verifications.

## Toolchain Baseline (P0-01)
- Git: `2.53.0.windows.2`
- Python: `3.12.5`
- uv: `0.11.5`
- Node.js: `v24.14.1`
- Docker: `29.6.1`

## Log Entries

### 2026-09-29 — P0-01 Local workspace and git
- **Task:** P0-01
- **What changed:** Initialized git repo connected to `https://github.com/bikash-barnwal/AssetFlow.git`, committed initial skeleton on `main`, created working branch `chore/P0-local-setup`, verified `.claude` hooks and test suite.
- **Evidence:** Clean git working tree, `python .claude/hooks/af.py status` operational, 25/25 hook tests passed in pytest.
- **Next step:** P0-02 (Old code test baseline).

### 2026-09-29 — P0-02 Old-code test baseline
- **Task:** P0-02
- **What changed:** Re-measured AssetManager test suites; ran backend unit tests with coverage, ran frontend Vitest suite, cataloged Playwright specs and un-tested features in `docs/tracker/baseline-assetmanager.md`.
- **Evidence:** Backend: 323 passed, 5 skipped (328 tests), 44% line coverage. Frontend Vitest: 164 passed across 18 files. Playwright: 17 specs across 8 files.
- **Next step:** P0-03 (License, provenance and sensitive-file scan).

### 2026-09-29 — P0-03 License, provenance and sensitive-file scan
- **Task:** P0-03
- **What changed:** Audited dependency licenses across Python and Node.js, cataloged bundled static assets/branding for replacement, documented NEVER COPY operational sensitive paths, and completed secret pattern scan.
- **Evidence:** `docs/provenance-scan.md` created with dependency, asset, sensitive-file, and secret finding tables (12 findings in assetmanager, 0 in TMMS-WEB, secret values suppressed).
- **Next step:** P0-04 (Domain-term inventory).

### 2026-09-29 — P0-04 Domain-term inventory
- **Task:** P0-04
- **What changed:** Scanned legacy codebases for single-tenant, proprietary, and industry terms; cataloged 1,898 occurrences across 140+ files; mapped each term to its neutral AssetFlow replacement in `docs/tracker/domain-terms.md`.
- **Evidence:** `docs/tracker/domain-terms.md` created with hit counts and replacement mapping (employee → member, department → org unit, authnexus → auth provider, it_ops → operator, jmv → assetflow).
- **Next step:** P0-05 (Repo tracker in loop format).

### 2026-09-29 — P0-05 Repo tracker in loop format
- **Task:** P0-05
- **What changed:** Created `docs/tracker/roadmap-tracker.md` matching loop table format; verified `python .claude/hooks/af.py next-task` correctly picks the next task (P1-01); all 25 hook tests green.
- **Evidence:** `docs/tracker/roadmap-tracker.md` present; `af.py next-task` returns valid JSON plan draft for P1-01; 25/25 pytest tests passed.
- **Next step:** P1-01 (Folder layout from §B4.3 and §C7.1).

### 2026-09-29 — P1-01 Folder layout from §B4.3 and §C7.1
- **Task:** P1-01
- **What changed:** Scaffolding complete for all 52 architectural directories across backend (app, providers, engines, modules, workers, migrations, tests), frontend (app, features, components, lib, styles), config, deploy, docs, scripts, and loadtest, each with a descriptive README.md.
- **Evidence:** 52 README.md files created; directory structure matches §B4.3 and §C7.1.
- **Next step:** P1-02 (License update Apache-2.0 → AGPL-3.0-only, CLA, REUSE).

### 2026-09-29 — P1-01 Folder layout from §B4.3 and §C7.1 (Follow-up)
- **Task:** P1-01
- **What changed:** Scaffolded the 7 missing §C7.1 docs directories (`docs/tutorials/`, `docs/explanation/`, `docs/guides/channels/`, `docs/guides/admin/`, `docs/reference/api/`, `docs/operations/runbooks/`, `docs/security/incidents/`) and created `docs/index.md`, each with a descriptive README and SPDX header.
- **Evidence:** All 7 directories present with README.md carrying AGPL-3.0 SPDX headers; Diátaxis docs layout fully represented.
- **Status:** ☑ (Verified via independent review check).

### 2026-09-29 — P1-02 License update, CLA, REUSE
- **Task:** P1-02
- **What changed:** Replaced root LICENSE with unmodified AGPL-3.0-only, added LICENSES/AGPL-3.0-only.txt, added CLA.md and NOTICE, updated README.md with dual-licensing policy, added REUSE.toml, verified 100% REUSE compliance (113/113 files).
- **Evidence:** `reuse lint` reports compliant; zero residual Apache text outside LICENSES/; head -3 LICENSE shows GNU AFFERO GENERAL PUBLIC LICENSE.

### 2026-09-29 — P1-03 Project docs
- **Task:** P1-03
- **What changed:** Written comprehensive governance and community documentation suite matching master plan M1.1-T2..T7 and §B12.1: `README.md`, `CONTRIBUTING.md`, `GOVERNANCE.md`, `SECURITY.md`, updated `CODE_OF_CONDUCT.md` to full Contributor Covenant 2.1 text (contact `conduct@tinyphi.com`), `SUPPORT.md`, `MAINTAINERS.md`, `CHANGELOG.md`, and validated `CLAUDE.md`.
- **Evidence:** All 9 doc files present and checked against master plan sections; `reuse lint` passes with 0 errors; verified against §B11.5 and §B12.1.

### 2026-09-29 — P1-04 .github files (written, not pushed)
- **Task:** P1-04
- **What changed:** Created GitHub configuration suite conforming to §B12.7 and §C5.8: PR template (`.github/pull_request_template.md`), 7 issue templates, label taxonomy (`.github/labels.yml`), `docs/operations/ci-cd.md`. Updated `CODEOWNERS` so that `@TinyPhi/assetflow-security` is the sole owner of all security paths.
- **Evidence:** Security paths in CODEOWNERS owned exclusively by `@TinyPhi/assetflow-security`; templates adhere to §B12.7.
- **Status:** ☑ (Verified via independent review check).


### 2026-09-29 — P1-05 ADRs 0001–0018
- **Task:** P1-05
- **What changed:** Authored all 18 Architecture Decision Records (`ADR-0001` through `ADR-0018`) in `docs/decisions/` following §C6.5 template and §B3 specifications. ADR-0011 updated with explicit revisions from Decisions 51 & 52 (OpenBao credentials + Zitadel multi-org identity). ADR-0010 (License) is `Proposed` pending Q17; the remaining 17 ADRs are `Accepted`. Indexed all ADRs in `docs/decisions/README.md`.
- **Evidence:** `(Get-ChildItem docs/decisions).Count` equals 19 (18 ADRs + README); ADR-0011 contains Decisions 51 and 52; `reuse lint` passes on all ADRs.

### 2026-09-29 — P1-06 Provenance record
- **Task:** P1-06
- **What changed:** Created comprehensive provenance record `docs/provenance.md` tracking all 39 components across §B14.1 (AssetManager -> AssetFlow, 32 items) and §B14.2 (TMMS -> AssetFlow, 7 items). Recorded source snapshot commit SHAs (`babc8ccba170c9b42ee72e21f2e8beb4ab0fbc66` for AssetManager, `d422c1067a760a8e0df5ac843b4c9efe5a14c859` for TMMS-WEB). Documented clean-room rules and OpenWind IP attribution policy.
- **Evidence:** 39 rows documented in `docs/provenance.md` matching §B14; `reuse lint` reports 100% compliance.

### 2026-09-30 — P2-01 to P2-12 Tooling, local CI, Zitadel and OpenBao
- **Task:** P2-01 to P2-12
- **What changed:** backend and frontend projects, Makefile, check scripts, pre-commit, CI workflows; OpenBao and Zitadel as code with multi-organization; Zitadel setup reworked OpenWind style (decision 53); setup guides in docs/guides/.
- **Evidence:** make verify passed in Docker; actionlint clean; REUSE compliant; 25 hook tests and 12 bootstrap tests pass; live Zitadel bootstrap 19 changes then 'No changes'; org A token resourceowner:id == org A; gitleaks: no leaks. PR #2.
- **Next step:** P3-01 (config loader).

### 2026-10-03 — P5-00 to P5-10 Organization structure and access (M1.4)
- **Task:** P5-00 to P5-10
- **What changed:** `assetflow org create` CLI and service; org unit/location/team trees with atomic materialized-path moves, cycle prevention and named archive blockers; `AuthMiddleware` resolving each request's member context fresh (no cache) via `platform.resolve_organization` and the organization's sign-in provisioning policy (`invite_only`, `require_role`, `open`), fail-closed while an organization is suspended; scoped role grants (`organization`/`org_unit`/`team`) with `can_grant` requiring the granter to already hold every permission being granted; organization settings read/update API; audit store with automatic PII redaction; module installation guard (`require_module`); bulk import of org units, teams and members (preview validates and writes nothing, commit is one all-or-nothing transaction, idempotent on business key). Corrected a self-introduced 403/404 inconsistency (writes denied by scope now answer 403, reads 404, per the master plan's own error-class table) across role grants, bulk import and organization settings. Security review found and fixed two issues before any PR was opened: JWT verification no longer treats a missing `exp` claim as non-expiring or an empty JWKS as "skip signature check"; a suspended organization no longer auto-provisions a new member.
- **Evidence:** Full backend suite 338/338; `tests/isolation tests/scope` 80/80; ruff, mypy, `check-schema-snapshot.sh check` (upgrade/downgrade/upgrade roundtrip), `check-domain-terms.py`, `check-migrations.py`, `check-docs-links.py` (145 files) all pass on the combined integration branch (`feat/31-p5-acceptance`, merging `feat/29-bulk-import` + `feat/28-module-installation` + `feat/30-organization-settings-api`); `reuse lint` (397/397 files compliant); `gitleaks` over the 58 commits since `main` (no leaks); `scripts/tests` 17/17; `tests/contract` 91/91; `.claude/hooks/tests` 25/25. New docs: `docs/specs/tenancy-and-scopes.md`, `docs/guides/admin/organization-structure.md`, `docs/guides/admin/roles-and-scopes.md`. PRs #47-#54 opened against `main` (not yet merged); P5-00 (`chore/19-db-login-naming`, PR #20) is a separate, independent branch, confirmed not an ancestor of this stack — its reconciliation with Phase 5 is deferred to the actual upstream merge, not forced locally.
- **Status:** ☑ (local; verified open for the owner — see TRACKER.md for per-plan detail and PR links).
- **Next step:** owner review/merge of PRs #47-#54, then Phase 6 / M1.5 (notifications and worker).

### 2026-10-04 — P6-01a Worker process and outbox dispatcher
- **Task:** P6-01a (issue #59, M1.5-T1 part a)
- **What changed:** migration `0009_worker_support` (`platform.list_active_organizations()`, `outbox.dead_lettered_at`, partial claim index); `worker_context`, `worker_claim_transaction` and `connect_direct` in `app/core/db.py`; `backend/workers/` with the dispatcher (claim with `SKIP LOCKED`, 5-minute reclaim, dead letter at `workers.outbox.max_attempts`, idempotent subscribers through `processed_events`), subscriber registry and `python -m workers.main` (LISTEN wake-up, poll backup, heartbeat, clean SIGTERM); `workers` config section; `af-worker` compose service; `docs/operations/worker.md`. Owner approved the dead-letter default (5) and column on 2026-10-04.
- **Evidence:** `tests/isolation tests/scope` 83/83, `tests/integration -k "outbox or worker"` 11/11, unit/contract/e2e_api 251/251, ruff, mypy (`app workers`), check-migrations, check-domain-terms, schema-snapshot upgrade/downgrade/upgrade; the worker image ran as non-root with a read-only root against a migrated database: processed a seeded row, healthcheck 0, SIGTERM exit 0 in 2 s, no published port.
- **Next step:** P6-01b (job runner and housekeeping).

### 2026-10-04 — P6-06a to P6-09 Notifications: channel runtime, channels, preferences, acceptance (M1.5 complete, local)
- **Task:** P6-06a, P6-06b, P6-06c, P6-04, P6-05, P6-07, P6-08, P6-09 (issues #64-#71, M1.5-T4 to T8 and acceptance)
- **What changed:** channel runtime (credentials only in OpenBao, write-only for the API; egress client: HTTPS, allowlist, public addresses, checked-address connect, no redirects); notification sender (3 attempts, circuit breaker, dead letter with admin alert and audit note, kill switch); channel installations, delivery log and re-queue API; `email` (SMTP, STARTTLS/TLS) and signed `webhook` channels; member preferences with mandatory in-app; channel settings as JSON Schema; `make new-channel`; generated events reference; docs. Migrations 0013-0015.
- **Evidence:** full backend suite 789 passed, 2 skipped; acceptance e2e `reports/p6-acceptance.xml` (2 passed, real Mailpit); `scripts/tests` 42; migration roundtrip and snapshot; gitleaks over 15 commits clean. Details in each plan's Record.
- **Status:** ☑ (local, not pushed; PRs only when the owner says).
- **Next step:** Phase 7 (M1.6).
