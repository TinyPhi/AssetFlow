<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# ADR-0001: Python 3.12 / FastAPI Modular Monolith with React 19 SPA

- **Status:** Accepted
- **Date:** 2026-09-23
- **Deciders:** Lead Architect, TinyPhi Engineering
- **Revisions / Supersedes:** Reaffirmed in §B1.3, §B4.1.

---

## 1. Context and Problem Statement

AssetManager possesses a proven, layered architecture (FastAPI router -> service -> repository) with asyncpg raw SQL and React frontend. The TMMS vision requires maintenance workflows and scheduling. AssetFlow is built by a small engineering team and targeted for single-node to modest multi-node self-hosting. Operational complexity must be minimized without compromising clean architectural boundaries.

---

## 2. Decision Outcome

Build AssetFlow as a modular monolith in Python 3.12 / FastAPI accompanied by a React 19 single-page application (SPA). Code from AssetManager serves as the operational baseline, ported module-by-module into a unified deployable artifact (`assetflow-api`), with async background processing handled by a companion worker process (`assetflow-worker`).

---

## 3. Consequences

### Positive & Negative Impact
- Good: Drastically lower operational overhead compared to microservices; simple single-command deployment.
- Good: Retains proven high-performance FastAPI/asyncpg patterns from AssetManager.
- Cost: Architectural boundaries between modules must be strictly guarded by `import-linter` in CI to prevent spaghetti dependencies.

---

## 4. Alternatives Considered

- Microservices architecture: Rejected due to prohibitive operational complexity, network latency, distributed transactions, and deployment friction for self-hosters.
- Full rewrite in Go or Rust: Rejected because it discards mature, tested business logic and slows down delivery without sufficient justification.

---

## 5. References

- Master Plan §B3 (D1), §B4.1, §B4.2, §C4.1.
