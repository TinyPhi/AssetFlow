<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# ADR-0012: Neutral Domain Vocabulary and Configurable Display Labels

- **Status:** Accepted
- **Date:** 2026-09-23
- **Deciders:** Lead Architect, Product Management
- **Revisions / Supersedes:** Reaffirmed in §C1.2, §B2.1 (419 legacy references eliminated).

---

## 1. Context and Problem Statement

AssetManager contained 419 hardcoded references to proprietary company names, IT-specific terms ('employee', 'laptop', 'IT Ops'), and vendor gateways. TMMS contained Telecom-specific branding. A unified platform must serve hospitals, data centers, and transit authorities without code changes.

---

## 2. Decision Outcome

Enforce a strictly neutral, domain-agnostic vocabulary in all database schemas, code symbols, API paths, and internal documentation. Standard terms are: `organization`, `org_unit`, `team`, `member`, `location`, `asset`, `work_order`, `work_request`. Industry-specific naming (e.g. 'Department', 'Ward', 'Technician', 'Ticket') is handled purely via UI translation and domain display labels.

---

## 3. Consequences

### Positive & Negative Impact
- Good: Single clean codebase adapts to any industry domain without branching or hardcoded conditionals.
- Good: Automated CI check (`scripts/check-domain-terms.sh`) blocks proprietary or industry-specific terminology in commits.
- Cost: Developers must adhere strictly to the standardized nomenclature table (§C1.2).

---

## 4. Alternatives Considered

- Allowing industry terms in code: Rejected because it creates severe cognitive friction and tight coupling across unrelated modules.

---

## 5. References

- Master Plan §B3 (D12), §C1.1, §C1.2, §C9.4.
