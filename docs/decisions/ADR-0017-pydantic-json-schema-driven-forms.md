<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# ADR-0017: Pydantic JSON Schema-Driven Connector and Provider Configuration

- **Status:** Accepted
- **Date:** 2026-09-23
- **Deciders:** Lead Architect, Fullstack Team
- **Revisions / Supersedes:** Reaffirmed in §B6.3, §B7.1.

---

## 1. Context and Problem Statement

Adding new notification channels, custom domain templates, or authentication providers usually requires writing hand-crafted frontend forms, duplicating validation logic between TypeScript and Python, and constantly maintaining form UI code.

---

## 2. Decision Outcome

Require every connector, provider, and domain module to declare its configuration schema as a Pydantic v2 model. The backend exports these schemas as standard JSON Schema. The React frontend dynamically renders configuration forms and generates client-side Zod validation rules directly from the exported schema.

---

## 3. Consequences

### Positive & Negative Impact
- Good: Single source of truth in backend code automatically generates frontend UI forms, documentation, and validation.
- Good: Adding a new channel plugin requires zero frontend code changes.
- Cost: Frontend form engine must support rich JSON Schema field widgets.

---

## 4. Alternatives Considered

- Manual React form development per connector: Rejected due to duplicated maintenance overhead and frontend drift.

---

## 5. References

- Master Plan §B3 (D17), §B6.3, §B7.1.
