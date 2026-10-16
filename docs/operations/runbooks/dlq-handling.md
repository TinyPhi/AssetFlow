<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# Runbook: dead-letter handling (§B13.6)

Two things are called a dead letter. Both are kept, never silently dropped.

## Notification deliveries

A delivery is dead-lettered (`status = 'dead_lettered'`) when its 3rd attempt fails, when the
failure cannot be fixed by retrying (any 4xx, a refused egress, a template that cannot render), or
when a worker died during its last attempt (`error_code = 'worker_interrupted'`).

When it happens, in one transaction: organization admins receive an in-app notice, an audit event
`notification_delivery.dead_lettered` is recorded on the related record (or on the delivery itself
when the event had none), and an outbox event of the same name is queued.

### Triage

1. Open the admin notice or the audit timeline of the related record; note the `channel_key` and
   `error_code`.
2. Group by `error_code` in `notification_deliveries` (`status = 'dead_lettered'`): one code on many
   rows is one cause (a down relay, a wrong credential, a blocked host).
3. Fix the cause first. Re-queuing before that only dead-letters the rows again.

### Re-queue

Reset the row so the sender picks it up again: `status = 'pending'`, `attempts = 0`,
`error_code = NULL`, `next_retry_at = NULL`. The delivery keeps its `idempotency_key`, so a
delivery that actually reached the recipient before the failure was recorded is the only case that
can be sent twice. The channel installations API (a later plan) exposes this as an admin action;
until it ships, an operator does it with a SQL update under the organization's context.

## Outbox events

The outbox dispatcher dead-letters an event after `workers.outbox.max_attempts` failed attempts
(default 5): the row stays in `outbox` with `dead_lettered_at` set and the last error code in
`last_error`. After fixing the handler, replay a row by clearing `dead_lettered_at` and `last_error`
and setting `attempts = 0`.

## Retention

In-app notices are removed after `notifications.channels.inapp.retention_days` (default 180).
Processed outbox rows and processed-event markers are removed after 7 days by housekeeping.
