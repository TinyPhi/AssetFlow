<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# ADR-0019: Database Roles and Login Users Standard

- **Status:** Accepted
- **Date:** 2026-10-01
- **Deciders:** Lead Architect, Database Architect, Security Team
- **Revisions / Supersedes:** Standardizes implementation of master plan §B10 and migration 0000.

---

## 1. Context and Problem Statement

AssetFlow relies on PostgreSQL row-level security (RLS) and schema isolation for multi-tenancy. To enforce the principle of least privilege, the database security model must strictly separate privilege sets (which define permissions and RLS policies) from connection credentials (which authenticate individual processes).

Without a uniform naming standard, local development and minimal profiles risk introducing ad-hoc account names (e.g. `assetflow_*_user` or `assetflow_app`) that diverge from the production OpenBao architecture and conflict with migration `0000_roles` invariants.

---

## 2. Decision Outcome

Adopt a single standard for PostgreSQL roles across all environments (development, CI, staging, production):

1. **Group roles (`NOLOGIN`):** Define privilege sets and schema ownership.
   - `assetflow_api`: API process permissions (reads and writes tenant data under RLS; cannot create objects).
   - `assetflow_worker`: Asynchronous background worker permissions (outbox, sweeps; cannot create objects).
   - `assetflow_migrator`: Owns all application schema objects, runs Alembic migrations, has DDL privileges.
   - `assetflow_readonly`: Read-only reporting and analytical queries under RLS.
   - `assetflow_resolver`: Internal role owning `platform.resolve_organization()`; never granted to any login user.

2. **Login users (`LOGIN`):** Dedicated authentication identities, one per process kind, adhering to `assetflow_<kind>_login`:
   - `assetflow_api_login`: Member of `assetflow_api`.
   - `assetflow_worker_login`: Member of `assetflow_worker`.
   - `assetflow_migrator_login`: Member of `assetflow_migrator`.
   - `assetflow_readonly_login`: Member of `assetflow_readonly`.

3. **Role attributes:**
   - Every application and migrator role is configured with `NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION`.
   - Only the PostgreSQL bootstrap user (`postgres`) possesses `CREATEROLE` during initial cluster initialization.

4. **Credential and password management:**
   - Passwords are provided solely via the secrets provider (`file` provider in development, `openbao` in production).
   - Passwords are never placed in compose files, environment defaults, container image layers, or git-tracked files.
   - Rotation updates the secret in the vault/file store and runs `ALTER ROLE assetflow_<kind>_login WITH PASSWORD ...`.

---

## 3. Consequences

### Positive & Negative Impact
- Good: Enforces strict separation of privilege sets and credentials across all profiles.
- Good: Eliminates configuration drift between local compose environments and production OpenBao deployments.
- Good: Fully aligns with `0000_roles` migration assertions prohibiting `LOGIN` on group roles.
- Cost: Process startup requires explicit mapping from process credentials to the corresponding group role membership.

---

## 4. Alternatives Considered

- **Direct login to group roles (`CREATE ROLE assetflow_api LOGIN`):** Rejected because `0000_roles` enforces `NOLOGIN` to prevent privilege escalation and ensure auditable credential rotation per process instance.
- **`assetflow_*_user` naming convention:** Rejected in favor of `assetflow_*_login` to match the canonical example documented in `backend/migrations/versions/0000_roles.py`.

---

## 5. References

- Master Plan §B10, §B11, glossary "Database roles".
- `backend/migrations/versions/0000_roles.py`.
- Phase plan P5-00 (`P5-00-database-login-naming-and-role-standard.md`).
