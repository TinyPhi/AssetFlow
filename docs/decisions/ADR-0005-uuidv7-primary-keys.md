<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# ADR-0005: UUIDv7 Primary Keys and Configurable Human-Readable Sequences

- **Status:** Accepted
- **Date:** 2026-09-23
- **Deciders:** Lead Architect, Database Architect
- **Revisions / Supersedes:** Reaffirmed in §C1.4, §C4.8.

---

## 1. Context and Problem Statement

AssetManager used UUIDv4 primary keys and a PostgreSQL sequence for human tags (`AST-#####`). TMMS used a custom Snowflake ID generator which suffered from clock rollback vulnerabilities and integer truncation in JavaScript (> 2^53 - 1). Database clustering performance requires sequential primary key ordering.

---

## 2. Decision Outcome

Adopt UUIDv7 as the universal primary key format across all database tables. For human-facing identifiers (asset tags, work order numbers, work request numbers), use per-organization database sequences with configurable domain prefixes.

---

## 3. Consequences

### Positive & Negative Impact
- Good: UUIDv7 is 128-bit time-ordered, preventing B-tree index fragmentation in PostgreSQL without node coordination.
- Good: Fully native string representation in JSON APIs, eliminating JavaScript integer truncation risks.
- Cost: Requires UUIDv7 generation utility in backend core.

---

## 4. Alternatives Considered

- Snowflake IDs: Rejected due to clock synchronization drift issues and JavaScript 64-bit integer corruption in web browsers.
- Auto-incrementing 32/64-bit serial integers: Rejected because they leak record counts/business volume and cannot be generated client-side.

---

## 5. References

- Master Plan §B3 (D5), §B2.2, §C1.4.
