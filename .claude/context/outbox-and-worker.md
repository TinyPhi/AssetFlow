# Context: outbox and worker

Orientation for `backend/workers/`, `providers/events/`, service write paths and anything that emits events. Plan sections: D9, §B4.1, §B4.2 rule 4, §B6.2 (events), §B9.3, §B10 (reliable side effects), §B13.2, §C1.6 (event payload), §C4.3, §C8.4.

## Why

Side effects (notifications, schedule generation, follow-up work) must never be lost and must never slow a request. PostgreSQL is the bus: no Kafka or Redis required (D9). Delivery is **at-least-once**; consumers make duplicates harmless.

## Write path (in the API)

One transaction per service command (§C4.3): lock and load -> permission + scope on the record -> transition check -> versioned write -> `audit_events` row -> `outbox` row -> commit. The outbox row commits or rolls back with the change. Never call email, channels or external APIs inside a request.

## Event shape (§C1.6)

```
{event_id, event_type, schema_version, occurred_at, organization_id,
 actor: {member_id, client_id}, entity: {type, id, version}, data: {...}, trace_context}
```

- `event_type` is `<entity>.<what_happened>` (`asset.assigned`, `work_order.sla_breached`).
- Within a major version, only optional fields are added. Breaking change -> new `schema_version`; consumers accept every supported version.
- Payload models carry descriptions; they generate `docs/reference/events.md`.

## EventBusProvider (§B6.2)

- `publish(topic, event)`, `subscribe(topic, handler, group)`.
- `postgres` (default): outbox table, `LISTEN/NOTIFY` wake-up, `FOR UPDATE SKIP LOCKED` claiming. `inmemory`: tests only.
- Consumers record `processed_events` for idempotency; DLQ after N attempts.

## Worker process (`assetflow-worker`, §B9.3)

| Job | Frequency | Notes |
| --- | --- | --- |
| Outbox dispatcher | continuous (NOTIFY + 2 s poll) | claim, run subscribers under the row's organization context |
| Schedule evaluator | every minute | idempotent work order generation, next due date |
| SLA sweeper | every minute | four precomputed timers, one event per target and level |
| Acknowledgement sweeper | every 15 min | custody reminders and escalations |
| Due-soon / overdue | every 15 min | once per work order and threshold |
| Warranty sweeper | daily | `asset.warranty_expiring` |
| Notification sender | continuous | retries, idempotency, delivery log |
| Job runner | on demand | imports, exports, PDFs with time and memory limits |
| Housekeeping | daily | purge processed outbox / `processed_events` > 7 days, expired exports, old in-app notifications |

## Claim, then send, then record

1. Short transaction: mark rows claimed (`claimed_at`, `claimed_by`) with `SKIP LOCKED`; commit.
2. Outbound calls run **outside any transaction**.
3. Short transaction: record the result.
Claims older than 5 minutes return to the queue. No transaction stays open across a network call (`idle_in_transaction_session_timeout` is 30 s).

## Database access for the worker

- Role `assetflow_worker`, no `BYPASSRLS`.
- Cross-organization reads only of claiming columns on `outbox` and `maintenance_schedules` (narrow policies).
- Other sweeps: `platform.list_active_organizations()` then one short transaction per organization under `worker_context(organization_id)`.
- An isolation test proves the worker reads zero rows of other tables without a context.

## LISTEN and PgBouncer

PgBouncer runs in transaction mode and cannot carry `LISTEN`. Each API and worker process keeps **one dedicated direct connection** for `LISTEN` (outbox wake-up and `grants_changed`). Everything else goes through the pool.

## Tests you must write (§C8.4, §B10)

- Job function run directly, effects asserted.
- "Run twice" -> same effect (idempotency).
- "Two workers at once" for claiming jobs.
- Kill the worker mid-batch -> exactly one effect per event.
- Every service command asserts its outbox row.

## Metrics

`assetflow_outbox_lag_seconds` (alert above 5 minutes, §B13.4), `assetflow_notifications_failed_total`. Span `worker.<job>.run`.
