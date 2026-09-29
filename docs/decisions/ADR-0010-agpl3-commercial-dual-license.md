<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# ADR-0010: AGPL-3.0 License with Commercial Dual-Licensing and Contributor License Agreement

- **Status:** Proposed
- **Date:** 2026-09-23
- **Deciders:** TinyPhi Owners, Open Source Legal Counsel
- **Revisions / Supersedes:** Revised 2026-09-28 (Decisions 42 & 43): Replaces Apache 2.0 with AGPL-3.0-only plus commercial dual-licensing; CLA with TinyPhi as assignee. Status remains Proposed pending formal sign-off in Q17.

---

## 1. Context and Problem Statement

AssetFlow is a business-critical asset and maintenance platform. Permissive licenses (like Apache 2.0 or MIT) permit commercial cloud providers to host the software as a proprietary closed-source service without contributing improvements back to the community. Sustainable open-source stewardship requires strong copyleft protections paired with commercial licensing flexibility.

---

## 2. Decision Outcome

License AssetFlow under the GNU Affero General Public License v3.0 (`AGPL-3.0-only`). Offer proprietary commercial licenses through TinyPhi for organizations requiring closed-source redistribution or exemptions from network-copyleft terms. All outside contributors sign a Contributor License Agreement (CLA) assigning copyright to TinyPhi.

---

## 3. Consequences

### Positive & Negative Impact
- Good: Guarantees that SaaS providers hosting AssetFlow must release their modifications back to the open-source community.
- Good: Provides a viable commercial sustainability path for TinyPhi to fund ongoing full-time development.
- Cost: Some enterprises maintain blanket internal policies against AGPL software (mitigated by commercial licensing).

---

## 4. Alternatives Considered

- Apache 2.0 + DCO: Initially considered, but rejected because it enables proprietary cloud forks with zero community reciprocity.
- BSL / SSPL (Source-Available): Rejected because they are non-OSI approved licenses and harm developer trust in the community.

---

## 5. References

- Master Plan §B3 (D10), §B11.5, §B12.3, Decisions 1, 42, 43, Q17.
