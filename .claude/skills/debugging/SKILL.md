---
name: debugging
description: Prove-It debugging for AssetFlow - reproduce, write a failing test, localize, fix, verify. Use for "bug", "fix", "failing test", "flaky", "500 error", "wrong data", "leak between orgs", "CI red", "why does X fail".
---

# Debugging (Prove-It)

A fix without a test that fails before it and passes after it is not a fix. The loop's review gate enforces this:
`commit_type: fix` requires `repro_test` among the changed tests.

## 1. Reproduce

- Get the exact symptom: command, request, input, `request_id`, error `code`, CI job log (`gh run view <id> --log-failed`).
- Reproduce locally with the smallest command: `uv run pytest <path>::<test> -x -vv`, `make test-isolation`,
  or an API call against `make up-minimal`. Record the output.
- Can't reproduce after 2 honest attempts -> write what you tried to `docs/tracker/BLOCKERS.md` and ask for data. Do not guess-fix.

## 2. Failing test first

- Put the test where the behavior lives (§C8): `unit/` pure logic, `integration/` SQL/service/worker, `isolation/` or `scope/`
  for any cross-organization or cross-scope symptom, `contract/` for provider/channel, `e2e_api/` for a flow.
- Name it for the behavior: `test_<behavior>` (e.g. `test_sibling_unit_member_gets_404_for_work_order`); path contains the module area.
- Run it and confirm it fails for the reported reason (not an import error or fixture typo). Keep the failing output.
- Tenancy symptom: always add an isolation or scope test, even if the root cause is elsewhere.

## 3. Localize

- Bisect by layer: router -> service -> repository -> SQL/RLS -> migration; worker: claim -> send -> record.
- Check the usual AssetFlow suspects:
  - organization context not set (`ctx.db.transaction()` / `worker_context` missing) -> 0 rows or insert refused;
  - `ScopeFilter` branch missing or not de-duplicated -> duplicates or leaks;
  - `version` not in `WHERE` -> lost updates;
  - outbox work done inside the request or across a network call -> timeouts, duplicate side effects;
  - time read outside `core.clock` -> flaky tests;
  - policy without `WITH CHECK`, view without `security_invoker`.
- Use `git log -S '<symbol>' -- <path>` and `git bisect run uv run pytest <test>` for regressions.
- Read logs by `request_id`; never add logging of tokens, emails, names, bodies or SQL parameters to debug.

## 4. Fix

- Smallest change that makes the failing test pass, inside the plan's `scope_paths`. Root cause, not symptom
  (no `try/except: pass`, no retries hiding a race, no widened permission).
- If the fix needs a schema or API contract change not in the plan -> BLOCKER.
- If the bug class can recur, propose a guard (lint rule, contract test, check script) in the plan's follow-ups.

## 5. Verify

- The repro test now passes; run the whole affected suite, then the loop: DOCS (`af.py docs --touched`, e.g. CHANGELOG
  under Unreleased/Fixed) -> verifier agent (`af.py verify`) -> REVIEW with `"repro_test": "<path>"`.
- Revert the fix locally once (`git stash push <fix files>`) and confirm the test fails again; restore it.
- Same test still failing after 2 fix attempts -> stop, write `docs/tracker/BLOCKERS.md`.

## Flaky tests (§C8.9)

Reproduce by running the test in a loop (`for i in $(seq 30); do uv run pytest <test> -q || break; done`) and with `-n auto`; common causes are shared rows between tests,
real time, ordering assumptions in lists without `ORDER BY`, and unawaited tasks. Fix the cause; never add sleeps or retries to tests.

## Security bugs

A suspected vulnerability (cross-org read, auth bypass, secret exposure) is handled privately (§C5.6): do not describe it
in public issues, commits or PR text beyond the neutral fix; tell the lead engineer and run the `security-reviewer` agent.
A leaked secret: rotate first (§C5.7).
