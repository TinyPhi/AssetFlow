# Contributing to AssetFlow

Thank you for your interest in contributing to **AssetFlow**!

AssetFlow is designed for high reliability, strict multi-tenant security, and clean open-source maintainability. All contributions—whether code, documentation, tests, or bug reports—follow the standards detailed below.

---

If you discover a security vulnerability, do not open a public issue. Email
[security@tinyphi.com](mailto:security@tinyphi.com) with a description.

## 1. Contribution Terms

**Draft terms — not yet reviewed by a lawyer.** Submitting a pull request means you agree to the
terms below, or to [`CLA.md`](CLA.md) directly. The CLA Assistant bot asks you to sign by comment
on your first PR.

1. **The contribution is your own original work**, or you have sufficient rights to submit it, and
   you've disclosed in the PR description if it includes or is based on someone else's work.
2. **You irrevocably assign to Abhinav Mishra all copyright and patent rights in your
   contribution**, in exchange for a license back to you to keep using your own contribution
   however you like. This is an assignment of ownership, not just a license — see
   [`CLA.md`](CLA.md) for the full terms.
3. **If your employer has rights to intellectual property you create**, you confirm you have
   permission to contribute on this basis, or your employer has waived that right for this
   Project. If this applies to you, say so before contributing.

AssetFlow uses a CLA, not a Developer Certificate of Origin (DCO): **do not include `Signed-off-by`
lines** in your git commits.

AssetFlow is released under the [GNU Affero General Public License v3.0](LICENSE). The assignment
above is what lets the project also be offered under a separate commercial license.

---

## 2. The Nine Non-Negotiables

Every contribution must respect the core engineering non-negotiables (Master Plan §B3, §C1):

1. **Fail-Closed Multi-Tenancy**: Every tenant table must have `organization_id NOT NULL`, PostgreSQL RLS enabled and forced (`ALTER TABLE ... FORCE ROW LEVEL SECURITY`), four fail-closed policies (SELECT, INSERT, UPDATE, DELETE), and an `organization_id`-first index. Views must be created with `WITH (security_invoker = true)`.
2. **Strict Scope Checks**: Permission and organizational scope must be validated on loaded entities (`ctx.scope.require`). All list queries take a mandatory `ScopeFilter`. Access violations return `404 Not Found` (never 403) to prevent resource enumeration.
3. **Transactional Outbox for Writes**: State mutations, audit records, and domain event outbox rows must commit in a single database transaction. External API calls or side-effects inside HTTP request handlers are prohibited.
4. **Zero Production Secrets in Code**: All server-side secrets reside in **OpenBao** (or environment overrides in local dev). Config references use `secret://` URIs. The frontend browser runtime never handles raw credentials.
5. **Privacy & Redaction**: No Personally Identifiable Information (PII) in logs, OpenTelemetry traces, or metric tags. Use pseudonymous member IDs only.
6. **Config-First & Neutral Vocabulary**: Zero company-specific, product-specific, or single-industry terms in core code. Industry terminology lives exclusively in declarative domain templates (`config/domains/*.yaml`). See [`docs/tracker/domain-terms.md`](docs/tracker/domain-terms.md).
7. **Conventional Commits**: Every commit follows the Conventional Commits 1.0.0 specification with an approved scope.
8. **Security-Sensitive Path Reviews**: Any change touching security-sensitive paths (§C5.8) requires explicit security reviewer approval.
9. **AI-Assisted Code Integrity**: AI-generated code is held to the identical quality and testing gates as human-written code. The human submitter is solely responsible for understanding and validating all code submitted.

---

## Local Setup

1. `make deps`: backend (uv) and frontend (npm) dependencies, pre-commit hooks.
2. `make bootstrap` (Windows: `setup.bat`): local Zitadel and its configuration; see [docs/guides/setup-zitadel.md](docs/guides/setup-zitadel.md).
3. `make verify` before every pull request: it runs everything CI runs.

Local secrets live in `.env.local` (git-ignored). Never commit it; production secrets live only in OpenBao ([docs/guides/setup-openbao.md](docs/guides/setup-openbao.md)).

## 3. Git Conventions & Branching

### Branch Names
- Format: `<type>/<task-id>-<short-kebab-desc>`
  - Example: `feat/M1.4-T3-member-provisioning`
  - Example: `fix/M2.2-T5-custody-ack`
- If contributing from an issue: `<type>/<issue-number>-<short-desc>` (e.g. `feat/142-floating-schedules`).
- **Never commit directly to `main`.** `main` is protected and always releasable.

### Commit Messages
Format: `type(scope): subject`
- **Type**: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `chore`, `ci`, `build`, `style`, `revert`.
- **Scope**: `core`, `organization`, `assets`, `maintenance`, `notifications`, `audit`, `workflow-engine`, `automation-engine`, `provider-<name>`, `channel-<name>`, `worker`, `web`, `config`, `deploy`, `docs`, `ci`.
- **Subject**: Imperative, lowercase, no trailing period, max 72 characters.
- Example: `feat(maintenance): add floating schedule evaluator`

---

## 4. Definition of Done (§C11)

A task or pull request is done only when:
1. **Acceptance Criteria**: All acceptance criteria defined in the task plan pass.
2. **Test Coverage**:
   - Unit and integration tests cover new and changed functionality.
   - Any new or modified database table includes isolation and scope leakage tests in `backend/tests/isolation/`.
   - Bug fixes include a regression test that fails without the fix.
3. **Quality Gates Pass Locally**:
   - `make lint` passes (ruff, prettier, import-linter, domain-term scan).
   - `make typecheck` passes (mypy for backend, tsc for frontend).
   - `make test` and `make test-isolation` pass with zero failures.
   - `uvx --with charset-normalizer reuse lint` reports 100% compliance.
4. **Documentation**:
   - Configuration keys, API routes, or domain events are documented in `docs/`.
   - Progress notes are appended to [`docs/tracker/PROGRESS.md`](docs/tracker/PROGRESS.md).
