<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# ADR-0018: Time-Limited Audited Break-Glass Access for Identity Provider Outages

- **Status:** Accepted
- **Date:** 2026-09-23
- **Deciders:** Lead Architect, Security Team
- **Revisions / Supersedes:** Reaffirmed in §B11.9, §C5.4.

---

## 1. Context and Problem Statement

In production environments, AssetFlow delegates authentication to external identity providers (Zitadel, Keycloak, etc.). If the IdP suffers an outage, network partition, or misconfigured certificate, administrators could be locked out of critical asset and maintenance infrastructure with no recovery mechanism.

---

## 2. Decision Outcome

Implement a local, host-initiated break-glass emergency recovery tool (`assetflow-admin break-glass`). The tool executes exclusively from the host shell, creates a short-lived (maximum 4 hours) cryptographic administrative session token, and immediately generates an immutable high-severity audit event that triggers notification alerts to all registered organization administrators upon system recovery.

---

## 3. Consequences

### Positive & Negative Impact
- Good: Ensures guaranteed operational survivability during external identity provider catastrophes.
- Good: Prevents dangerous permanent backdoor accounts or static emergency passwords in the database.
- Cost: Operators must maintain secure host shell access to initiate recovery.

---

## 4. Alternatives Considered

- Hardcoded static 'emergency' local admin credentials: Rejected due to extreme vulnerability to brute-force and credential stuffing attacks.
- Direct manual database record manipulation: Rejected because it bypasses application invariant checks, tenancy hooks, and audit trails.

---

## 5. References

- Master Plan §B3 (D18), §B11.9, §B13.5.
