<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# ADR-0015: Built-in Inbox and First-Party In-Process Notification Channel Connectors

- **Status:** Accepted
- **Date:** 2026-09-23
- **Deciders:** Lead Architect, Integration Team
- **Revisions / Supersedes:** Reaffirmed in §B6.3, §C6.7.

---

## 1. Context and Problem Statement

Third-party notification management platforms (such as Novu or Courier) add substantial operational complexity and external service dependencies. Conversely, hardcoding external channel APIs directly into core business services creates tight coupling and credential leakage risks.

---

## 2. Decision Outcome

Build notifications directly into AssetFlow. 1.0 includes an in-app notification inbox and an SMTP email channel. All outbound destinations (Slack, MS Teams, Webhooks, WhatsApp) are built as first-party, in-process `NotificationChannel` connectors governed by strict runtime constraints: encrypted credential storage, egress IP/host allowlisting, and per-tenant kill switches.

---

## 3. Consequences

### Positive & Negative Impact
- Good: Zero external cloud services required for basic notification functionality; completely self-contained.
- Good: Standardized connector plugin architecture allows community members to easily add new channels.
- Cost: AssetFlow core must maintain delivery retry loops and dead-letter queue tables.

---

## 4. Alternatives Considered

- Adopting Novu or external notification SaaS: Rejected to maintain self-contained, minimal deployment capability.
- Inline synchronous notification dispatch: Rejected due to severe request latency and unavailability risks.

---

## 5. References

- Master Plan §B3 (D15), §B6.3, §C6.7.
