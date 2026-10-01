# Definition of Done

Copied from plan §C11 (master checklist). A change is done only when **every applicable item** is true. The reviewer agent records `dod_met` (and `dod_unmet` items) with `python .claude/hooks/af.py review set`; the commit gate refuses when `dod_met` is not `true`.

## Code

- [ ] Follows the module structure and patterns (§C4) and the nomenclature (§C1).
- [ ] No business logic in routers; no SQL outside repositories; no vendor SDK outside providers and channels.
- [ ] Writes use one transaction with audit and outbox; versioned updates check `version`.
- [ ] New routes have a permission and a rate limit; new list methods take a `ScopeFilter`.
- [ ] No secrets, personal data or raw tokens in code, logs, fixtures or tests.
- [ ] New files carry SPDX license headers (or a `REUSE.toml` entry).
- [ ] Errors are raised as module errors and returned as RFC 9457 problems.

## Data

- [ ] New tables and views meet §C4.8; the migration has a working downgrade.
- [ ] Indexes support the new queries (checked with `EXPLAIN` on realistic demo data for list queries).

## Tests

- [ ] Unit and integration tests cover the behavior, including failure paths.
- [ ] Tenant-isolation tests (organization and scope) cover new tables, views and endpoints.
- [ ] API E2E tests cover new user-facing flows.
- [ ] New or changed screens were checked at the §C8.7 widths and with the keyboard.
- [ ] Coverage does not drop.

## Security

- [ ] The PR's security notes are filled in.
- [ ] The security reviewer approved changes on security paths.

## Docs

- [ ] Required docs from §C7.2 are written or updated; generated reference docs are regenerated.
- [ ] CHANGELOG updated for user-visible changes.
- [ ] UI text exists in `en.json` (no raw text in components).

## Process

- [ ] The author has accepted the CLA, and commits follow Conventional Commits.
- [ ] CI is green; the contribution checks pass.
- [ ] The linked issue will close on merge.

---

## Related checks (not part of §C11, listed for convenience)

From §B12.3 item 6, also expected in the PR:

- [ ] Migrations pass the migration lint (`scripts/check-migrations.py`).
- [ ] New events are documented in `docs/reference/events.md` (generated from payload models).
- [ ] New config keys are documented and validated (Pydantic field with description).

From §C7.2, the docs each change needs:

| Change | Required docs |
| --- | --- |
| New or changed API endpoint | OpenAPI from code (docstring summary, field descriptions, examples); `error-codes.md` regenerated |
| New config key | Pydantic field description (generates `config.md`); example in the relevant guide |
| New event type | Payload model with descriptions (generates `events.md`) |
| New permission | Declared in `permissions.py` with a description; default roles in `assetflow.yaml` if needed |
| New notification channel | `docs/guides/channels/<key>.md` |
| New screen or changed flow | User guide page, screenshots (light theme, 1440 px) |
| Operational change | `docs/operations/` page and release-notes "Upgrade notes" |
| Architectural decision | ADR |
| Non-trivial feature | Spec |
| Any user-visible change | CHANGELOG entry under "Unreleased" |

Loop-specific evidence (enforced by the hooks, see `.claude/README.md`): `af.py verify` passed on the current diff; tests changed in the same area as the source (or a `tests_waiver` in the plan); a `fix` has a `repro_test`; a migration comes with an isolation or scope test change.
