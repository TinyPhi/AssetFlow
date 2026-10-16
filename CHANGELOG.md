<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- **Tooling & local CI (P2-01 to P2-06)**: backend project (uv, FastAPI stub, ruff, mypy strict, pytest, import-linter contracts); frontend project (Vite, React 19, strict TypeScript, ESLint with jsx-a11y, vitest); Makefile with `make verify` as the single local gate; check scripts (domain terms, migration lint, contribution guardrails, license allowlist, docs links); pre-commit and commitlint; CI workflows (ci, security, contribution checks, CLA, scorecard, dependabot).
- **Identity & secrets (P2-07 to P2-12)**: OpenBao from HCL config with policies, KV v2, transit and AppRole applied by `scripts/openbao-apply.py`; self-hosted Zitadel with one-command setup (`scripts/bootstrap.sh`, `setup.bat`) and the idempotent `scripts/bootstrap_zitadel.py`: project, roles, apps, automation user, one Zitadel organization per `config/organizations/*.yaml` with project grants; startup order and smoke test.
- **Guides**: `docs/guides/setup-zitadel.md` and `docs/guides/setup-openbao.md`.
- **Organization structure and access (M1.4, P5-00 to P5-10)**: `assetflow org create` command; org unit, location and team trees with atomic path recomputation and archive blockers; sign-in member provisioning policies (`invite_only`, `require_role`, `open`); scoped role grants (organization/org-unit/team/self) with a `can_grant` privilege check; organization settings API; audit store with PII redaction; module installation from domain templates; bulk import of org units, teams and members (preview/commit, all-or-nothing, idempotent). Every tenant table has `organization_id NOT NULL`, forced row-level security and four fail-closed policies; every state change writes an audit event and outbox row in the same transaction.
- **Worker (M1.5-T1a, P6-01a)**: separate `assetflow-worker` process with an outbox dispatcher (`FOR UPDATE SKIP LOCKED` claiming, 5-minute reclaim, dead letter after `workers.outbox.max_attempts`, idempotent subscribers), `platform.list_active_organizations()`, `outbox.dead_lettered_at`, the `workers` config section and an `af-worker` service in `deploy/compose.minimal.yml`. See `docs/operations/worker.md`.
- **Notifications (M1.5, P6-00 to P6-09)**: notification tables (channel installations, in-app inbox, delivery log, preferences); a job runner, scheduler and housekeeping in the worker; the automation engine (event -> condition -> recipients -> channels -> template) with `assetflow config validate` checking every rule; the in-app channel and inbox API; a channel runtime that gives each send its credentials and an HTTP client that reaches only allowlisted, public hosts (credentials only in OpenBao, write-only for the API); a notification sender with 3 attempts (1 s, 4 s), a circuit breaker, dead letter, an admin in-app alert and an audit note, and a kill switch; channel installations, delivery log and re-queue API; the `email` channel (SMTP with STARTTLS or TLS, per-organization sender) and the signed `webhook` channel (declarative field mapping, HMAC-SHA256 signature, 5-minute timestamp window); member notification preferences with mandatory in-app; each channel's settings as JSON Schema; `make new-channel name=<key>`; and a generated events reference (`make docs-generate`). Migrations 0010 to 0015.
- **Guides and reference**: `docs/guides/channels/email.md`, `docs/guides/channels/webhook.md`, `docs/guides/writing-a-notification-channel.md`, `docs/guides/admin/notifications.md`, `docs/explanation/outbox-and-worker.md`, `docs/explanation/notifications.md`, `docs/operations/secrets.md`, the SMTP-outage and dead-letter runbooks, and the generated `docs/reference/events.md`.
- **Asset domain-template sections (M2.1 input, P8-01)**: the `assets` section of a domain template (tag format, statuses with categories, structured transitions, categories with custom fields, criticality, public scan fields, public report, acknowledgement timings, owner-follows-holder and member-move cascade), validated at boot and by `assetflow config validate` with exact error paths; shipped in two templates, `config/domains/it-assets.yaml` and `config/domains/facilities.yaml`.
- **Guides**: `docs/guides/admin/create-organization.md`, `docs/guides/admin/member-provisioning.md`, `docs/guides/admin/organization-structure.md`, `docs/guides/admin/roles-and-scopes.md`, and `docs/specs/tenancy-and-scopes.md`.
- **Asset data and catalog (M2.1, P8-01 to P8-12)**: asset tables (categories tree, custom field definitions, manufacturers, suppliers, assets, components, meters, readings, per-organization number sequences, saved views) with forced row-level security and trigram, scope and custom-field indexes (migrations 0016 to 0020); custom fields of seven types with every rule validated and encrypted fields (one provider call per write, hidden from lists, shown only with `asset.read_sensitive`); asset tags generated per organization from the template format; the asset API (create, edit with version check and `Idempotency-Key`, detail, list with fuzzy search, filters, `cf.<key>` filters, sorting, cursor pages, saved views); lifecycle statuses and transitions from the domain template (`409 asset.invalid_transition`); components that move with their parent; catalog reference data API with template seeding; the asset list, detail, create/edit and category administration screens; `GET /api/v1/assets/vocabulary`. Scope refusals on writes now answer `403 scope.denied` (no grant for the permission still answers `auth.permission_denied`).
- **Guides**: `docs/guides/assets/catalog.md` (asset user guide) and `docs/guides/composing-a-domain.md` (asset sections of the domain template, with both shipped templates as examples).
- **Database roles standard (P5-00)**: ADR-0019 standardizing database group roles (`NOLOGIN`) and dedicated process login users (`assetflow_<kind>_login`), operations documentation, and consistency test.

### Security
- **Audit remediation (2026-10)**: OIDC checks `iss`, `aud` (required outside development/test) and `nbf`/`iat` (60 s leeway) and requires an `https://` issuer with no silent discovery fallback; `env` has no default and every boot guard applies to all environments except `development` and `test` (so `staging` is guarded); the session cookie key comes from OpenBao and boot refuses without it; real PKCE (S256), `state` and `nonce` in the sign-in flow; the rate limiter trusts `X-Forwarded-For` only from configured proxy CIDRs; access tokens are short-lived (5 minutes) and the revocation set is capped; the OpenBao token is renewed before expiry, with `ca_cert`/`BAO_CACERT` support; the transit key `assetflow-fields` is created derived (an existing non-derived key is refused; see `docs/operations/runbooks/rekey-transit-derived.md`, local test data encrypted with it is lost); the log scrubber covers phones, IP addresses, bare JWTs and token-shaped strings; `/docs`, `/redoc` and `/openapi.json` are off in production. See `docs/security/audit-remediation.md`.

### Changed
- Zitadel configuration moved from OpenTofu to the bootstrap script (master plan decision 53).
- Loop helper `af.py verify` runs verify commands without a shell.
- Standardized database login user naming to `assetflow_<kind>_login` across `deploy/postgres/init-minimal.sh`, `config/assetflow.yaml`, and `deploy/compose.minimal.yml`.
- Minimal profile: roles and logins are applied by a one-shot `db-roles` service on every start (not only on a new database); existing `assetflow_<kind>_user` logins are renamed automatically.

### Earlier (P0–P1)
- **Repository Architecture & Layout**: Created directory skeleton conforming to §B4.3 modular monolith and §C7.1 documentation structure.
- **Licensing & Compliance**:
  - Adopted GNU Affero General Public License v3.0 (`AGPL-3.0-only`) with dual commercial licensing availability.
  - Implemented Contributor License Agreement (`CLA.md`) and attribution `NOTICE`.
  - Configured REUSE specification (`REUSE.toml`) with verified SPDX license compliance across 100% of repository assets.
- **Project Governance & Community**:
  - Established project `GOVERNANCE.md` detailing consensus rules, maintainer roles, and RFC procedures.
  - Established `CONTRIBUTING.md` defining setup, branch strategy, testing standards, and Definition of Done.
  - Established `CODE_OF_CONDUCT.md` adopting Contributor Covenant v2.1.
  - Established `SECURITY.md` defining coordinated vulnerability disclosure and ASVS L2 target.
  - Established `SUPPORT.md` outlining community and commercial support paths.
  - Established `MAINTAINERS.md` cataloging role definitions and review scope.
  - Configured `CLAUDE.md` engineering instructions for AI-assisted workflows and quality gates.
- **Auditing & Scan Reports**:
  - Conducted Phase 0 baseline scans for domain terms, licensing provenance, and credential protection.
