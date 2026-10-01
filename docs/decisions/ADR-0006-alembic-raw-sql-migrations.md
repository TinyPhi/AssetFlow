<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# ADR-0006: Alembic Raw SQL Migrations and Security Invoker Views

- **Status:** Accepted
- **Date:** 2026-09-23
- **Deciders:** Lead Architect, Database Team
- **Revisions / Supersedes:** Reaffirmed in §C4.8, §C5.4.

---

## 1. Context and Problem Statement

AssetManager lacked an automated migration tool, leading to schema drift in production. However, AssetManager's asyncpg raw SQL repositories delivered exceptional query performance (586 req/s). ORM migrations often obscure complex PostgreSQL features like RLS policies, functional indexes, and GiST/ltree.

---

## 2. Decision Outcome

Use Alembic as the migration runner, but write all migrations as explicit, version-controlled raw SQL (`op.execute(...)`). Every migration must include symmetric `upgrade()` and `downgrade()` methods. Prohibit database schema dumps. Enforce that all views declare `WITH (security_invoker = true)` so they inherit the querying user's RLS constraints.

---

## 3. Consequences

### Positive & Negative Impact
- Good: Absolute transparency and predictability of SQL statements executed in production; no ORM magic.
- Good: CI automatically validates migrations via `upgrade head -> downgrade -1 -> upgrade head` drills.
- Cost: Developers must author SQL DDL statements manually, including rollback logic.

---

## 4. Alternatives Considered

- Full ORM adoption (SQLAlchemy ORM / Tortoise): Rejected due to performance overhead and impedance mismatch with advanced PostgreSQL RLS/ltree features.
- Schema dumps (`pg_dump`): Rejected because dumps cannot model incremental versioned deployments or clean rollbacks.

---

## 5. References

- Master Plan §B3 (D6), §C4.4, §C4.8.
