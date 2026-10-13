<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# Worker process

`assetflow-worker` (`python -m workers.main`, container `af-worker` in the minimal profile) turns
outbox rows into effects. The API only writes the change, its audit event and its outbox row in one
transaction; the worker does everything that happens afterwards (§B9.3, §B10).

## How an event is handled

1. **Claim.** One short transaction claims up to `workers.outbox.batch_size` rows with
   `FOR UPDATE SKIP LOCKED`, so several workers never take the same row.
2. **Run.** Each subscriber of the event type runs in its own transaction under the event's
   organization. It first records `(consumer, event)` in `processed_events`; a repeat of the same
   event is skipped, so a retry or a restart never doubles an effect.
3. **Record.** Success sets `processed_at`. A failure stores the error class (never the message) in
   `last_error` and returns the row to the queue.

No database transaction stays open across a step, and a subscriber makes no network call.

## Retries, reclaim and dead letter

| Situation | What happens |
| --- | --- |
| Subscriber raises | `attempts` counts claims; the row is retried on the next poll |
| `attempts` reaches `workers.outbox.max_attempts` (default 5) | `dead_lettered_at` is set, the row is no longer claimed, `outbox.dead_lettered` is logged and `assetflow_outbox_dead_lettered_total` counts it |
| Worker dies after claiming | The claim expires after `workers.outbox.reclaim_after_seconds` (default 300); another worker claims the row. Rows already at `max_attempts` are dead-lettered with `last_error = ClaimExpired` |
| SIGTERM | The row in progress finishes; claimed rows not started are released without counting an attempt |

Find dead-lettered events: `SELECT id, organization_id, event_type, last_error, dead_lettered_at
FROM outbox WHERE dead_lettered_at IS NOT NULL` (run as an operator; the worker role has no
business reading them by hand). To retry one after fixing the cause, set `dead_lettered_at = NULL`
and `attempts = 0`.

## Configuration (`config/assetflow.yaml`, `workers`)

| Key | Default | Meaning |
| --- | --- | --- |
| `workers.outbox.batch_size` | 50 | Rows claimed per batch |
| `workers.outbox.poll_interval_seconds` | 2 | Poll interval when no NOTIFY arrives |
| `workers.outbox.reclaim_after_seconds` | 300 | Age after which a claim is returned to the queue |
| `workers.outbox.max_attempts` | 5 | Claims before dead letter |
| `workers.outbox.listen_host` / `listen_port` | `database.host` / `database.port` | Direct PostgreSQL address for LISTEN; set it when `database.behind_pgbouncer` is true (LISTEN does not work through PgBouncer transaction pooling) |
| `workers.heartbeat_file` | `/tmp/af-worker-heartbeat` | Touched every loop; the healthcheck reads its age (30 s) |

## Database access

The worker connects as the `assetflow_worker` login and holds no `BYPASSRLS`. It sees all
organizations only through the narrow claim policies on `outbox`. Sweeps over other tables call
`platform.list_active_organizations()` and then work in each organization's own transaction.

## Health and telemetry

`python -m workers.main --healthcheck` exits 0 while the heartbeat is fresh. Span
`worker.outbox_dispatcher.run` per batch; metrics `assetflow_outbox_lag_seconds` and
`assetflow_outbox_dead_lettered_total`; log fields `organization_id`, `event_type`, `error_code` only.
