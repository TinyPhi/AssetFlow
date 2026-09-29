<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# AssetFlow Maintainers

This document lists the project maintainer roles, responsibilities, and the governance expectations for maintainers of AssetFlow.

For project decision rules, voting, and RFC processes, please refer to [`GOVERNANCE.md`](GOVERNANCE.md).

---

## 1. Maintainer Roles

To maintain clear separation of responsibilities and adhere to governance guidelines (§B12.1), the project defines the following maintainer roles:

| Role | Focus Area | Responsibilities | Contact / Review Scope |
| --- | --- | --- | --- |
| **Lead Maintainer** | Architecture & Roadmap | Overall architectural integrity, roadmap milestones (Gate G0–G5), final sign-off on breaking changes and core ADRs. | `lead@assetflow.org` / Repo-wide |
| **Security Maintainer** | Security & Privacy | ASVS L2 compliance, cryptographic policy, OpenBao & Zitadel configuration, tenant RLS isolation reviews (§C5.8), CVE coordination. | `security@tinyphi.com` / Security paths |
| **Backend Maintainer** | Platform Core & API | FastAPI application, domain engines, database migrations, worker dispatcher, provider interfaces, test coverage. | `backend-team@assetflow.org` / `backend/`, `config/` |
| **Frontend Maintainer** | Web Shell & UX | React 19 SPA, design token system, state management, accessibility (WCAG 2.1 AA), i18n, Playwright E2E suites. | `frontend-team@assetflow.org` / `frontend/` |
| **DevOps & Infra Maintainer** | Deployment & CI | Docker Compose profiles, CI/CD GitHub Actions workflows, OpenBao/Zitadel infrastructure, Helm/Kubernetes manifests. | `infra-team@assetflow.org` / `deploy/`, `.github/` |

---

## 2. Maintainer Responsibilities

Maintainers agree to:
- Review pull requests within 3 business days of submission.
- Ensure that every approved pull request meets the [Definition of Done](.claude/references/definition-of-done.md), includes tests, and adheres to our security non-negotiables.
- Enforce the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md).
- Guard security-sensitive paths (§C5.8) requiring mandatory second-reviewer sign-off.
- Keep the project dependencies and security scanners green.

---

## 3. Becoming a Maintainer

AssetFlow welcomes active contributors to join maintainer roles based on sustained merit and trust:
1. Demonstrated record of high-quality pull requests and constructive code reviews over at least 3 months.
2. Adherence to project architectural principles, neutral domain vocabulary, and test-driven development.
3. Nomination by an existing maintainer followed by consensus among the maintainer group per [`GOVERNANCE.md`](GOVERNANCE.md).

---

## 4. Inactivity and Emeritus Status

Maintainers who have been inactive for more than 6 months will be transitioned to Emeritus status to keep operational review queues responsive. Emeritus maintainers may be reinstated upon resuming active contributions.
