<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# Notifications (organization admin)

Admins decide which channels the organization uses and can see what was sent. Members choose, for
themselves, which of those channels they want for each kind of event.

All routes are under `/api/v1/notification-channels`. You need the `notification_channel.manage`
permission to change anything and `notification_channel.read` / `notification_delivery.read` to look.

## Channels

| Channel | What it does | Guide |
| --- | --- | --- |
| In-app | the member's inbox; always on, needs no setup | n/a |
| Email | mail through the platform's SMTP relay, from your sender address | [email](../channels/email.md) |
| Webhook | a signed request to a URL you choose, with fields you map | [webhook](../channels/webhook.md) |

`GET /notification-channels` lists what can be installed. `GET /notification-channels/<key>/schema`
returns the settings of a channel as JSON Schema, with secret fields marked write-only; the admin
form is built from it.

## Install, change, switch off

- **Install:** `POST /installations` with the channel key, its settings and any secrets. Secrets go
  straight to the secrets provider and are **never shown again**: every response shows a secret only
  as `{"set": true}`.
- **Change:** `PATCH /installations/<id>` with the `version` you read (a stale version is a 409). A
  secret you leave out keeps its stored value; send `null` to clear an optional one; send a new value
  to rotate it.
- **Kill switch:** `POST /installations/<id>/disable` stops sending at once (the next claim skips the
  channel's deliveries) without deleting anything; `POST /installations/<id>/enable` resumes. The
  platform admin uses the same endpoint through a grant in your organization.

## The delivery log

`GET /deliveries` lists every delivery, newest change first, with its channel, member id, status
(`pending`, `sending`, `sent`, `failed`, `dead_lettered`, `skipped`), attempts, latency and error code.
Filter by `status`, `channel` and `since`; page with `after` (the `next_cursor` of the previous page).
It never shows an address or a message body.

## When a delivery fails

A failing channel is retried 3 times (1 s, then 4 s apart). If the last attempt fails, the delivery is
**dead-lettered**: you (every admin) get an in-app notice, and an audit event is written on the
record the event was about. Fix the cause (the relay, the credential, the receiver), then
`POST /deliveries/<id>/requeue` to send it again. See the [SMTP outage](../../operations/runbooks/smtp-outage.md)
and [dead-letter](../../operations/runbooks/dlq-handling.md) runbooks.

## Member preferences

Each member reads and changes only their own choices at `/api/v1/me/notification-preferences`: a
matrix of every event type by every channel installed and enabled (plus in-app). Everything is on by
default. In-app cannot be switched off for an event your automation rules mark `mandatory`.

## Data protection

An installation's `allow_personal_data` (off by default) decides whether fields a template or an
event marks personal can leave AssetFlow. Switch it on only for a destination you trust with them.
