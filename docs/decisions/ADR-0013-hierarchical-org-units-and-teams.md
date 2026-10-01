<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# ADR-0013: Hierarchical Org Units via PostgreSQL Ltree and Cross-Cutting Teams

- **Status:** Accepted
- **Date:** 2026-09-23
- **Deciders:** Lead Architect, Database Architect
- **Revisions / Supersedes:** Reaffirmed in §B5.2, §B10.

---

## 1. Context and Problem Statement

AssetManager used a flat `departments` table without parent-child hierarchies or team constructs. Real enterprises require multi-tier organization trees (Enterprise -> Division -> Region -> Facility) with cross-cutting functional teams (e.g., Electrical Maintenance Crew) for dispatch and task assignment.

---

## 2. Decision Outcome

Model organizational units (`org_units`) and physical locations (`locations`) as trees using PostgreSQL's native `ltree` extension with materialized paths and GiST indexing. Model `teams` as separate, cross-cutting entities that group members regardless of their organizational unit.

---

## 3. Consequences

### Positive & Negative Impact
- Good: Subtree querying and permission inheritance are blisteringly fast via indexed `ltree` operators (`<@`, `@>`).
- Good: Clean separation between administrative hierarchy (reporting lines) and operational dispatch (teams).
- Cost: Moving an org unit node in the tree requires cascading materialized path updates on children.

---

## 4. Alternatives Considered

- Recursive Common Table Expressions (CTEs): Rejected due to query performance degradation on deep hierarchies.
- Nested Sets model: Rejected because inserting or rebalancing nodes requires expensive table-wide lock updates.

---

## 5. References

- Master Plan §B3 (D13), §B5.2, §B10.
