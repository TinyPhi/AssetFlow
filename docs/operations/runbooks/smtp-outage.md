<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# Runbook: SMTP outage (§B13.6)

The email channel cannot reach its SMTP server (relay down, wrong credentials, network blocked).

## What happens on its own

1. The outbox dispatcher keeps queuing deliveries: every email an automation produces is written as a
   `pending` row in `notification_deliveries`. In-app notices are unaffected.
2. The notification sender tries each delivery up to **3 times**. After a failed attempt it waits
   **1 s** (after the 1st) and **4 s** (after the 2nd) before trying again. Only timeouts,
   connection errors and 5xx answers are retried; a 4xx (for example a rejected sender address) is
   not, because sending the same request again changes nothing.
3. After **5 consecutive failures** on the channel installation, its circuit opens for **30 s**.
   While it is open, deliveries stay queued and the skipped attempt is **not** counted, so a long
   outage does not burn the 3 attempts of everything in the queue. After 30 s one trial call runs:
   success closes the circuit, failure reopens it.
4. A delivery that fails its 3rd attempt is **dead-lettered**: it stops retrying, every active
   organization admin gets an in-app notice (`delivery-dead-lettered`), an audit event
   `notification_delivery.dead_lettered` is written on the related record, and an outbox event is
   queued.

## What to check

- `notification_deliveries` rows with `channel_key = 'email'` and their `status` / `error_code`
  (`timeout`, `connection_error`, `http_…`, `platform.secrets_unavailable`, `channel.egress_denied`).
  The code is never a server message, so it holds no address.
- `channel.egress_denied`: the SMTP host is not on the channel's allowed hosts, or it resolves to a
  private address. This is configuration, not an outage; fix the installation and re-queue.
- `platform.secrets_unavailable`: OpenBao is sealed or unreachable (see the OpenBao runbook).
- Telemetry: `assetflow_notifications_failed_total` and `assetflow_notifications_dead_lettered_total`
  (tagged by `channel_key` only).

## Recovery

1. Fix the cause (restore the relay, correct the credentials, unseal OpenBao).
2. Deliveries still `pending` or `failed` send by themselves on the next pass; nothing to do.
3. Dead-lettered deliveries do not retry on their own: re-queue them as described in
   [DLQ handling](dlq-handling.md).
4. To stop sends while you work, disable the channel installation (the kill switch): its queued
   deliveries become `skipped` with `channel.disabled`, nothing is deleted.
