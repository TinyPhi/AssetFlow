# AssetFlow Governance Model

This document outlines the project governance structure, decision-making framework, and maintainer responsibilities for the **AssetFlow** open-source project.

---

## 1. Project Stewardship

AssetFlow is an open-source project stewarded by **TinyPhi**. TinyPhi provides infrastructure, architectural guidance, commercial dual licensing, and overall legal stewardship for the codebase.

The goal of this governance model is to ensure sustainable long-term development, transparent community participation, and high architectural integrity.

---

## 2. Roles and Responsibilities

All participants hold one of the following roles:

| Role | Responsibilities | Requirements |
| --- | --- | --- |
| **Contributor** | Submits bug fixes, features, documentation, and tests. Participates in community discussions. | Signed Contributor License Agreement ([`CLA.md`](CLA.md)); adherence to [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md). |
| **Reviewer** | Reviews pull requests for quality, domain-term neutrality, and test coverage. | Active track record of high-quality contributions; thorough understanding of architectural guidelines. |
| **Security Reviewer** | Reviews changes touching security-sensitive paths (`backend/app/core/permissions`, auth providers, secrets, migrations). | Named in [`CODEOWNERS`](.github/CODEOWNERS); deep familiarity with OWASP ASVS and PostgreSQL RLS. |
| **Maintainer** | Triages issues, approves and merges PRs, cuts releases, and enforces coding standards. | Consistent contribution history; vote of confidence from existing maintainers. |
| **Lead Maintainer** | Guides project roadmap, resolves architectural deadlocks, and oversees milestone delivery. | Appointed by TinyPhi. |

*(For current role holders, see [`MAINTAINERS.md`](MAINTAINERS.md).)*

---

## 3. Decision-Making Framework

AssetFlow values transparency and technical consensus.

### Routine Changes (Lazy Consensus)
- Routine bug fixes, documentation improvements, and incremental features are decided through lazy consensus during PR review.
- Requires at least one approving review from a maintainer and passing CI checks.

### Architectural Decisions (ADR Process)
- Any significant architectural change, database design alteration, provider interface change, or protocol shift requires an **Architecture Decision Record (ADR)** submitted to `docs/decisions/`.
- ADRs follow the template in `docs/decisions/` and must specify:
  1. Context and problem statement
  2. Decision and proposed implementation
  3. Consequences (tradeoffs and operational impact)
  4. Rejected alternatives
- An ADR requires approval from the Lead Maintainer and relevant component maintainers.

### Escalation & Disagreements
If consensus cannot be reached after constructive technical debate, the **Lead Maintainer** makes the binding decision, prioritizing security, multi-tenant safety, and long-term sustainability.

---

## 4. Path to Maintainership

Contributors who consistently submit high-quality code, demonstrate good technical judgment, and actively help review other community pull requests can be nominated as maintainers by any existing maintainer. Maintainership is confirmed by unanimous agreement of the current maintainer team.
