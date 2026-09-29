---
description: Turn a reviewed spec into phased acceptance criteria and freeze the first phase as the plan (af.py plan set)
argument-hint: "<docs/specs/<name>.md> [phase number, default 1]"
---

PLAN step driven by a spec. Do not edit source files in this command.

1. Read the spec `$ARGUMENTS`. If it has not had `/spec-review` with `READY` or `READY WITH CAVEATS`, run `/spec-review` first
   and stop on `NOT READY`.
2. Split the spec into phases. Each phase is one branch, one plan, one PR, reviewable in one sitting. Default order:
   1. data: migration(s) + isolation/scope tests (security-reviewer and migration-reviewer will run);
   2. repository + service + events: unit and integration tests (success, permission refusal, scope refusal,
      version conflict, invalid transition, audit row, outbox row);
   3. routes: `require(...)` / `public_route(rate_limit=...)`, authz-matrix, API E2E, generated docs;
   4. worker jobs / channels / providers: run-twice and two-workers tests, contract suites;
   5. UI: feature folder per §C4.9, i18n keys, four list states.
   Skip phases the spec does not need; never mix a migration and UI in one phase.
3. For each phase write acceptance criteria `AC1..ACn`: one observable behavior each, with the command that proves it
   (`uv run pytest <path> -k <name>`, `make test-isolation`, `make test-contract`, `make docs-check`, `make config-validate`).
   Trace each criterion to the spec section it comes from (`spec: Design/API`).
4. Show all phases as a table (phase, criteria, scope_paths, security paths touched, migration yes/no) and ask the lead engineer
   to confirm the split. Record the phase list in the spec's `## Verification` section only if they agree.
5. Build the plan JSON for the requested phase (default 1):
   - `task_id`: the tracker id if the spec maps to one, else `<tracker milestone>-<spec-name>-P<n>`;
   - `commit_type`, `spec_ref` (the spec path), `adr_refs`;
   - `acceptance_criteria` from step 3 (`done: false`);
   - `scope_paths`: exact prefixes for this phase only, plus `docs/tracker/`, the spec file and `CHANGELOG.md` when user-visible;
   - `tests_waiver`: empty.
6. Create the branch if not on one: `git switch -c <type>/<issue>-<short-kebab>`.
7. Freeze: write the JSON to a scratch file, then `python .claude/hooks/af.py plan set < <scratch>/plan.json`.
8. Ask: "Type `approve-plan` to approve phase <n>, or tell me what to change." Stop until the human approves.

If a criterion cannot be made testable, or the phase needs an API/schema contract the spec does not define,
write the question to `docs/tracker/BLOCKERS.md` and stop.
