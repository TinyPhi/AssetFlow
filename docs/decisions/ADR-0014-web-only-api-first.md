<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# ADR-0014: Web-Only 1.0 Release with API-First Design

- **Status:** Accepted
- **Date:** 2026-09-23
- **Deciders:** Lead Architect, Product Management
- **Revisions / Supersedes:** Reaffirmed in §B1.3, §B4.5, Decisions 8 & 33.

---

## 1. Context and Problem Statement

Building native mobile apps (iOS/Android) concurrently with the 1.0 platform skeleton overextends a small team and delays delivering the core asset and maintenance engines. However, field technicians must be able to use the software on mobile phones.

---

## 2. Decision Outcome

Limit AssetFlow 1.0 client scope to a responsive web application (supporting mobile and desktop browsers on Chromium and Safari). Architect the entire backend strictly API-first (`/api/v1`) with full OpenAPI documentation and RFC 9457 error contracts, enabling native mobile applications to be developed in Phase 4 / 1.x without backend changes.

---

## 3. Consequences

### Positive & Negative Impact
- Good: Keeps 1.0 scope focused and achievable for a single-engineer milestone delivery.
- Good: Responsive web interface provides immediate mobile access for field technicians on smartphones.
- Cost: Offline data synchronization must wait for the future native application release.

---

## 4. Alternatives Considered

- Simultaneous React Native / Flutter apps in 1.0: Rejected due to excessive build, test, and maintenance overhead.
- Server-rendered web templates: Rejected because the interactive maintenance boards require rich client-side SPA state.

---

## 5. References

- Master Plan §B3 (D14), §B1.3, §B4.5, Decision 8.
