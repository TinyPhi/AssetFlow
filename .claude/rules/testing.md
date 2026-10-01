---
paths:
  - "backend/tests/**"
  - "frontend/**/*.test.*"
  - "loadtest/**"
---

# Testing rules

Source: plan §B10, §B11.6, §B12.4, §C8.1–§C8.11. Commands: `make test`, `make test-backend ARGS="-k name"`, `make test-isolation`, `make test-contract`, `make test-e2e-api`, `make verify`.

## Layout

| Kind | Location | Tools |
| --- | --- | --- |
| Unit (backend) | `backend/tests/unit/` | pytest, pytest-asyncio, time-machine, hypothesis |
| Integration | `backend/tests/integration/`, `backend/tests/contract/`, `backend/tests/authz_matrix/` | pytest on real PostgreSQL 16, respx |
| Tenant isolation | `backend/tests/isolation/`, `backend/tests/scope/` | two organizations, an org unit tree, teams |
| API E2E | `backend/tests/e2e_api/` | pytest + httpx against the running app (mock auth, Mailpit) |
| Unit (frontend) | `frontend/src/**/*.test.ts(x)` | vitest, Testing Library, MSW |
| Load (on demand) | `loadtest/scenarios/` | k6; not a CI gate |

Names: `test_<unit>.py` with `test_<behavior>` functions (`test_dispatch_requires_permission`); `<unit>.test.ts(x)`. Name test files after the area they cover: the review gate matches changed source areas (`assets`, `core`, `auth`, ...) against changed test paths.

## Database

- **Never mock the database** for repository, service, worker or isolation tests. Use a real PostgreSQL 16 with the real migrations applied.
- A fresh, migrated database per test session (suite); each test isolates itself in its own transaction or its own organization, so tests run in parallel (`pytest -n auto`) and in any order.
- Unit tests touch no database, network or file system.

## Test data (§C8.2)

- Build data with factories in `backend/tests/factories.py` (`make_organization()`, `make_org_unit(parent=...)`, `make_team()`, `make_member(roles=..., scope=...)`, `make_asset()`, `make_work_order()`, `install_module(org, "maintenance", template="facilities")`). **Factories go through services**, not raw inserts, so audit and outbox rows exist as in production.
- Standard fixtures: `org_a`, `org_b`, `tree` (Operations -> North -> Depot 7, sibling South), `crew` (lead + technician), `as_member(role, scope)`.
- Never use demo data. Never real personal data: Faker with a fixed seed, `example.org` emails, `+91-00000-0000x` numbers. No secrets in fixtures; generate values.
- Freeze time with `time-machine`; code reads time only through `core.clock`.
- Include non-Latin text (for example Devanagari) in template and PDF tests.

## What each change needs

- **Service command:** success, permission refusal, scope refusal, version conflict, invalid transition, audit row written, outbox row written.
- **Worker job:** effects of one run; "run twice" idempotency; "two workers at once" for claiming jobs.
- **Config-driven rules:** table-driven tests over the whole priority matrix, every workflow transition (allowed and refused), each condition operator.
- **Invariants with hypothesis:** SLA clock never goes backward; pausing and resuming never shortens a deadline; the four SLA timers (`sla_response_warn_at`, `sla_response_breach_at`, `sla_resolution_warn_at`, `sla_resolution_breach_at`) keep each warning at or before its breach; the scope resolver never grants more than the union of grants.
- **Every tenant table / view / repository read method / endpoint:** isolation suite coverage (read isolation, unstamped zero rows, cross-organization write refused, foreign ids -> 404). Required in the same diff as any migration (the commit gate checks it).
- **Scope suite:** sibling org unit 404 and absent from lists; parent manager allowed; revoked grant refused on the next request; a record matching two branches listed once.
- **Authorization matrix:** every OpenAPI route has a permission or a `public` marker; each role gets 2xx/validation 4xx when permitted and 403/404 when not. Exceptions only in `exceptions.yaml` with a reason.
- **Provider/channel:** the contract suite with `@contract_target("<key>")` and recorded HTTP; channels also cover schema export, write-only secrets, egress enforcement (including a host re-resolving to `127.0.0.1`), 5xx/timeout retries, no retry on 4xx, idempotency, personal-data filtering, health.
- **User-facing flow:** an API E2E test. The test clock endpoint exists only when `ASSETFLOW_ENV=test`.
- **Frontend:** hooks and components; every `t()` key exists in `en.json`; source scans (no hardcoded colors, raw UI strings, `console.*`).

## Prove-It rule for fixes

A `fix` commit needs a **reproduction test** that fails without the change and passes with it. Record it as `repro_test` in `af.py review set`; it must be among the changed tests. Write the test first, watch it fail, then fix.

## Behaviour, not implementation

- Assert inputs -> outputs, raised module errors, HTTP status and RFC 9457 `code`, audit and outbox rows. Do not assert private calls or SQL text.
- Never weaken, skip or delete a failing test to get green. After 2 failed fix attempts, write `docs/tracker/BLOCKERS.md`.

## Coverage and flakiness

- Floors: `core`, `engines`, `providers`, `channels` 85% line / 75% branch; `modules` 75% / 65%; frontend `lib/` and hooks 80%; components 60%. Coverage must not drop on any PR.
- Flaky test: fix within 1 working day or mark `@pytest.mark.quarantine` / `test.fixme` with an issue number. More than 3 quarantined blocks feature merges.

## Load tests

- `make loadtest USERS=100` creates and deletes its own organization; virtual users spread over org units and teams. Results to `loadtest/results/<date>-<git-sha>.json` and `docs/operations/performance.md`.
