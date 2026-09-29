<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# ADR-0007: Permission-Based Scoped Role-Based Access Control

- **Status:** Accepted
- **Date:** 2026-09-23
- **Deciders:** Lead Architect, Security Architect
- **Revisions / Supersedes:** Reaffirmed in §B5.3, §C5.4.

---

## 1. Context and Problem Statement

AssetManager used three hardcoded roles (`employee`, `admin`, `it_ops`), which prevented granular delegation and department-level administration. Enterprise organizations require permissions scoped to specific branches of their organizational hierarchy or operational teams.

---

## 2. Decision Outcome

Implement fine-grained, permission-based Role-Based Access Control (RBAC) with hierarchical scoping. Application code checks granular permissions (`ctx.scope.require('asset.transfer', record)`). Roles are named bundles of permissions defined in configuration. A role is granted to a member at a specific scope: `self`, `team`, `org_unit` (with subtree inheritance), or `organization`.

---

## 3. Consequences

### Positive & Negative Impact
- Good: Extreme flexibility: organizations can create custom roles or restrict a manager's visibility to their own division.
- Good: Code never references role names, only immutable granular permissions.
- Cost: Authorization resolver must evaluate scope hierarchies on loaded records; queries need `ScopeFilter`.

---

## 4. Alternatives Considered

- Hardcoded role enumerations: Rejected because they fail multi-department enterprise delegation requirements.
- Attribute-Based Access Control (ABAC) engine (e.g. OPA / Rego): Rejected as overly complex for 1.0 scope; scoped RBAC covers 100% of requirements.

---

## 5. References

- Master Plan §B3 (D7), §B5.3, §C4.3, §C5.4.
