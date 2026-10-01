<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# ADR-0009: Transactional Outbox Pattern and Dedicated Background Worker

- **Status:** Accepted
- **Date:** 2026-09-23
- **Deciders:** Lead Architect, Backend Team
- **Revisions / Supersedes:** Revised 2026-09-28 (Decision 49 & 50): Claim-then-send outbox model; dedicated direct LISTEN connection outside PgBouncer.

---

## 1. Context and Problem Statement

AssetManager sent emails inline during HTTP requests, leading to observed 6-second request latencies and dropped notifications when external SMTP servers hung. TMMS used Kafka directly without an outbox, risking lost events if the transaction failed after publishing.

---

## 2. Decision Outcome

Implement the Transactional Outbox pattern with a dedicated background worker process (`assetflow-worker`). Every state-changing service command writes the entity update, audit log, and outbox event row in a single atomic database transaction. The worker claims outbox rows with `SELECT ... FOR UPDATE SKIP LOCKED` and notifies listeners via direct PostgreSQL `LISTEN/NOTIFY`.

---

## 3. Consequences

### Positive & Negative Impact
- Good: Zero lost events (at-least-once delivery guarantee); requests complete instantly (< 50ms) without waiting on external networks.
- Good: PostgreSQL handles the message bus natively in 1.0; no mandatory Kafka or RabbitMQ cluster required.
- Cost: Consumers must be idempotent to safely handle duplicate message deliveries.

---

## 4. Alternatives Considered

- Inline asynchronous tasks (`BackgroundTasks` in FastAPI): Rejected because tasks are lost if the server process restarts or crashes before completion.
- Mandatory external message queue (Kafka / RabbitMQ): Rejected to keep the minimal self-hosting stack lightweight.

---

## 5. References

- Master Plan §B3 (D9), §B4.1, §B9.3, §B13.2, Decisions 7, 49, 50.
