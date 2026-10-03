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
- **Guides**: `docs/guides/admin/create-organization.md`, `docs/guides/admin/member-provisioning.md`, `docs/guides/admin/organization-structure.md`, `docs/guides/admin/roles-and-scopes.md`, and `docs/specs/tenancy-and-scopes.md`.

### Changed
- Zitadel configuration moved from OpenTofu to the bootstrap script (master plan decision 53).
- Loop helper `af.py verify` runs verify commands without a shell.

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
