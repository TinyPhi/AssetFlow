<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# ADR-0004: Organization Multi-Tenancy Enforced via PostgreSQL Row-Level Security

- **Status:** Accepted
- **Date:** 2026-09-23
- **Deciders:** Lead Architect, Database & Security Teams
- **Revisions / Supersedes:** Reaffirmed in §B5.1, §B10, §C5.4.

---

## 1. Context and Problem Statement

AssetManager was strictly single-tenant. Retrofitting multi-tenancy late in an application's lifecycle is notorious for data leak vulnerabilities. Single-tenant installations and multi-organization hosted deployments must share the same codebase and architecture.

---

## 2. Decision Outcome

Enforce strict multi-tenancy at the database tier using PostgreSQL Row-Level Security (RLS). Every tenant-scoped table must have `organization_id NOT NULL`, `ALTER TABLE ... FORCE ROW LEVEL SECURITY`, four fail-closed policies (SELECT, INSERT, UPDATE, DELETE), and an `organization_id`-prefixed index. Connection sessions set `app.organization_id` via parameterized `set_config`. Missing context matches zero rows.

---

## 3. Consequences

### Positive & Negative Impact
- Good: Fail-closed security guarantee: even if an application bug omits a tenant filter in a query, PostgreSQL blocks data leaks across organizations.
- Good: Single-tenant and multi-tenant installations run the identical codebase.
- Cost: Every database migration requires automated tenant isolation tests (`backend/tests/isolation/`); views must declare `WITH (security_invoker = true)`.

---

## 4. Alternatives Considered

- Application-level `WHERE organization_id = ...` filtering: Rejected because a single developer oversight causes catastrophic cross-tenant data exposure.
- Schema-per-tenant or Database-per-tenant: Rejected due to migration orchestration nightmares and excessive connection pool resource consumption at scale.

---

## 5. References

- Master Plan §B3 (D4), §B5.1, §B10, §C4.8, §C5.4.
