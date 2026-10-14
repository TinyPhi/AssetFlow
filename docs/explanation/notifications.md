<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# How a notification is produced

An event becomes a notification in four steps. Each step has one job and none of them runs inside a
request (see [the outbox and the worker](outbox-and-worker.md)).

## 1. An automation rule decides who and how

The domain template of an organization (`config/domains/<domain>.yaml`) holds `automations`:

```yaml
automations:
  - when: team_member.added          # a registered event type
    if: {field: team_role, operator: equals, value: lead}    # optional structured condition
    then:
      recipients: [holder]           # holder, actor, team:<field>, role:<role>@<scope>
      channels: [inapp, email]
      template: team-member-added
      mandatory: false
```

The planner resolves the recipients (a role at a scope reaches everyone holding it there, including
through a parent org unit), applies the member's own preferences, and produces one **intent** per
(event, member, channel) with a deterministic idempotency key. A rule that names an unknown event,
field, channel, template or recipient keyword stops `assetflow config validate` with the exact path.

## 2. Preferences filter the intents

Each member can switch a channel off per event type. The default is on. Only a stored "off" removes
an intent, and in-app is never removed for a `mandatory` rule (a custody acknowledgement, for
example).

## 3. The channel gets the message

- **In-app** is written directly: a row in the member's inbox (deduplicated on the idempotency key)
  and a delivery-log row, in the same transaction.
- **Every other channel** is queued: a `pending` delivery-log row carrying the template, the event
  type, the related record and only the fields the template declares (payload minimization).
  Personal fields are kept only if the installation allows them. A channel the organization did not
  install queues nothing.

## 4. The sender delivers

The sender claims due deliveries (`FOR UPDATE SKIP LOCKED`), then, **outside any transaction**: checks
the kill switch (a disabled channel skips its deliveries) and the channel's circuit breaker, builds the
channel's context (credentials from the secrets provider, an allowlisted HTTP client, the recipient
lookup), renders the template and calls the channel. It records the outcome in a second short
transaction.

- A timeout, a connection error or a 5xx is retried: 3 attempts, 1 s then 4 s apart. A 4xx, a refused
  address or a template that cannot render is not retried.
- After the last failed attempt the delivery is **dead-lettered**: in the same transaction every
  organization admin gets an in-app notice, an audit event is written on the related record, and an
  outbox event is queued. An admin can send it again after fixing the cause.
- After 5 consecutive failures on one channel installation its circuit opens for 30 s and deliveries
  stay queued without using up their attempts; then one trial call decides.
- A delivery already sent is never claimed again. The one case that can send twice is a worker that
  dies after sending and before recording; the destination sees the same delivery id.

## What is kept, and what never is

The delivery log keeps the channel, the member id (never an address), the status, the attempt count,
the latency and an error **code**. It never keeps an email address, a message body or a server's
answer. Channel credentials are only in the secrets provider; the database holds a reference and the
names of the secret fields that have a value.
