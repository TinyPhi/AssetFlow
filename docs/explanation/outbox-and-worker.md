<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# The outbox and the worker

Nothing outside the database (an email, a webhook, a notice) is sent from inside a request. A change
writes what happened to the **outbox** in the same transaction as the change; a separate **worker**
process delivers the consequences afterwards. If the transaction rolls back, nothing was announced;
if the worker dies, nothing is lost.

## The outbox

Every state change writes three things in one transaction: the change, an audit event, and an
outbox row (`public.outbox`) holding the event type, the aggregate it is about and a flat JSON
payload. The payloads are listed in the [events reference](../reference/events.md).

## The worker

`python -m workers.main` runs beside the API as its own process, connected as the `assetflow_worker`
database role, which is granted only what it needs. It runs three loops:

1. **Outbox dispatcher.** It wakes on a PostgreSQL `NOTIFY` or every poll interval and claims a
   batch with `FOR UPDATE SKIP LOCKED`, so any number of workers can run at once and each row is
   handled by one. A claim older than 5 minutes is reclaimed. Each event goes to its subscribers; a
   subscriber is recorded as done per event (idempotent), so a retry never repeats a finished one. An
   event that fails `workers.outbox.max_attempts` times is dead-lettered and kept.
2. **Notification sender.** It sends the external deliveries the subscribers queued (see
   [notifications](notifications.md)).
3. **Scheduler.** Periodic jobs, one scheduler wins an advisory lock per tick. Housekeeping deletes
   processed outbox rows and processed-event markers after 7 days and in-app notices after the
   configured retention (180 days), per organization.

Every item runs under its own organization: the worker sets the organization context on its
connection (`worker_context`), so row-level security applies to it exactly as it does to the API. The
only cross-organization reads are narrow platform functions (the list of active organizations, one
organization's domain key).

## Why this shape

- **No lost or invented notifications.** The outbox row commits or rolls back with the change.
- **No slow work in a request.** A relay that is down never slows or fails an API call.
- **Safe to scale.** Claiming with `SKIP LOCKED` and per-event idempotency make a second worker an
  addition, not a risk.
- **Safe to stop.** SIGTERM finishes the item in progress and releases the unstarted claims; a worker
  that dies leaves claims that go stale and are reclaimed.

See [the worker operations page](../operations/worker.md) for running it.
