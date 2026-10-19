<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# Writing a notification channel

A channel is the way AssetFlow reaches someone outside the app: email, a webhook, a chat tool. This
is the path for adding one (master plan §C6.7). The built-in channels are the best examples:
`backend/app/channels/email.py` (SMTP) and `backend/app/channels/webhook.py` (signed HTTPS).

## 1. Propose it

Open a `channel.yml` issue. Describe the destination, how it authenticates, the hosts it needs to
reach and the personal data it would send. Wait for the issue to be accepted.

## 2. Scaffold it

```sh
make new-channel name=slack
```

This creates, and refuses to overwrite:

| File | Purpose |
| --- | --- |
| `backend/app/channels/slack.py` | the channel class |
| `backend/tests/contract/channels/test_slack.py` | tests specific to this destination |
| `backend/tests/contract/channels/fixtures/slack/ok.json` | a recorded response to replay |
| `docs/guides/channels/slack.md` | the setup guide |

and registers the channel in `backend/tests/contract/channels/channel_targets.py`, so the shared
contract checks run for it straight away.

## 3. Implement it

Fill in four things in the channel class:

- **`config_schema`**: a Pydantic model of the per-organization settings. Mark secrets with
  `SecretStr` and a `json_schema_extra={"writeOnly": True}`; list their names in `secret_fields`. The
  admin form is built from the schema `GET /api/v1/notification-channels/<key>/schema` exports, so
  give every field a `title` and a `description`.
- **`egress_hosts`**: every host the channel may call. Nothing else is reachable.
- **`send(ctx, target, message, idempotency_key)`**: deliver one message. Return a `DeliveryResult`;
  never raise for an ordinary failure.
- **`health(ctx)`**: report whether the channel works for the organization, without sending
  anything surprising.

The rules the runtime enforces and the contract suite checks:

- Reach the network **only** through `ctx.http`. It allows HTTPS to allowlisted hosts only, refuses
  any name that resolves to a private, loopback, link-local or reserved address, connects to the
  address that passed the check, and never follows a redirect.
- Read secrets **only** from `ctx.credentials`. The runtime reads them from the secrets provider for
  this one call; a channel never reads a secret itself, and a secret is never logged, returned by
  the API or stored in the database.
- `target` is a member id, never an address. Look the address up with `ctx.recipients`, keep it in
  memory for this send, and never write it to a log, a trace, a metric tag or the delivery log.
- Use `idempotency_key` as the destination's own delivery id (a webhook's delivery header, an email's
  `Message-ID`) so a receiver can drop the one possible duplicate.
- Classify failures with `app.channels.retry`: a timeout, a connection error or a 5xx is retryable;
  every 4xx is not. The sender retries 3 times (1 s, then 4 s apart), then dead-letters the delivery,
  tells the organization admins and notes the related record.
- Send only the fields a template declares; personal fields only when the installation allows it.
- A channel that wants something other than the template's fields in a pending delivery (a webhook
  maps event fields itself) overrides `build_message_data`; `accepts_event` skips events the
  installation did not ask for; `allowed_hosts_for` names the hosts the saved settings imply.

Register the class in `default_registry()` in `backend/app/channels/registry.py`. A package outside
this repository registers through the `assetflow.channels` entry point group instead.

## 4. Make the contract suite pass

```sh
make test-contract
```

It checks, for every registered channel: the settings schema exports and is valid JSON Schema;
secret fields are write-only (and never have a default); the channel declares its egress hosts;
health reports a flag. Add the checks your destination needs to `test_slack.py`: retries on 5xx and
timeouts, no retry on 4xx, idempotency, personal-data filtering. Replay recorded responses with
`httpx.MockTransport` behind the real `EgressClient` so the egress rules are exercised too; the
email tests use a local SMTP server with real TLS for the same reason.

## 5. Name it and document it

Add the display name `notification_channels.slack.name` to `frontend/src/lib/i18n/locales/en.json`
(the schema carries keys, not translated text). Fill in `docs/guides/channels/slack.md`: setup steps
on the destination's side with screenshots, and the list of everything that leaves AssetFlow.

Read the [email](channels/email.md) and [webhook](channels/webhook.md) guides for the shape.
