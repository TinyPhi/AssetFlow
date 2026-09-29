<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# ADR-0003: Pluggable Provider Interfaces for Core Infrastructure

- **Status:** Accepted
- **Date:** 2026-09-23
- **Deciders:** Lead Architect, Infrastructure Team
- **Revisions / Supersedes:** Revised 2026-09-29 (Decisions 51 & 52): Zitadel is the official OIDC preset; OpenBao is the mandatory production secrets backend; all server-side credentials stored in OpenBao.

---

## 1. Context and Problem Statement

AssetFlow requires authentication, secrets management, distributed telemetry, and transactional event distribution. Different deployment environments vary: self-hosters desire minimal dependencies, enterprise deployments require integration with centralized corporate vaults and identity providers.

---

## 2. Decision Outcome

Abstract all core infrastructure pillars behind abstract base class provider interfaces (`AuthProvider`, `SecretsProvider`, `TelemetryProvider`, `EventBusProvider`). AssetFlow 1.0 ships with exactly one production preset and one lightweight fallback per pillar: OIDC (Zitadel preset) + Mock; OpenBao + File/Env; OpenTelemetry OTLP + NoOp; PostgreSQL Outbox + In-Memory.

---

## 3. Consequences

### Positive & Negative Impact
- Good: Domain business modules remain completely decoupled from specific third-party SDKs.
- Good: Changing infrastructure backends requires only configuration changes, zero code edits.
- Cost: Must maintain comprehensive contract test suites (`backend/tests/contract/`) for each provider implementation.

---

## 4. Alternatives Considered

- Direct integration with vendor SDKs: Rejected because it hardwires the application to specific commercial or complex platforms.
- Supporting dozens of community providers in core 1.0: Rejected to protect scope and maintainability for a small engineering team.

---

## 5. References

- Master Plan §B3 (D3), §B6.1, §B6.2, §B11.2, §B11.4, Decisions 36, 51, 52.
