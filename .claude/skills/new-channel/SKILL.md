---
name: new-channel
description: Scaffold a notification channel connector (NotificationChannel) with its contract tests and guide, following §C6.7 and the §B6.3 runtime rules. Use for "new channel", "add Slack/Teams/Google Chat/WhatsApp", "make new-channel", "channel-<name>".
---

# New notification channel

Precondition: an accepted `channel.yml` issue describing destination, auth method, egress hosts, personal data sent;
an approved plan whose `scope_paths` include the files below.

## Scaffold

`make new-channel name=<key>` creates (with SPDX headers):

- `backend/app/channels/<key>.py`
- `backend/tests/contract/channels/test_<key>.py`
- `backend/tests/contract/channels/fixtures/<key>/` (recorded HTTP responses)
- `docs/guides/channels/<key>.md`

Also add the display name to the translation file (`en.json`, key under `notifications.channels.<key>`).
No frontend code: the settings form and Zod validator are generated from the JSON Schema at
`/api/v1/notification-channels/{key}/schema`.

## Implement

- `key = "<key>"`.
- `config_schema`: Pydantic model of per-organization settings; secrets as `SecretStr` (write-only, stored encrypted,
  never returned, shown as set / not set). Personal-data switch off by default.
- `egress_hosts`: exact hosts the channel may call (none for in-app).
- `send(ctx, message, target)`: use only `ctx.http` (the runtime's allowlisted client) and `ctx.credentials`.
  Return a result the runtime logs to `notification_deliveries`. Send the idempotency key
  (event, recipient, channel) as the destination's dedupe id / delivery id.
- `health(ctx)`.

Never: read secrets or env vars, create your own HTTP client, resolve DNS yourself, log credentials or message bodies,
call from inside a request or a DB transaction (the sender runs claim -> send outside a transaction -> record).

## Runtime guarantees you rely on (do not reimplement; `channels/base.py` is a security path)

- Credentials at `secret/assetflow/orgs/<organization_id>/channels/<channel_id>` in OpenBao, passed per call in `ChannelContext`.
- Egress allowlist; DNS re-checked every attempt including retries; private, loopback, link-local blocked; connect to the
  pinned checked address.
- Retries 3 attempts (1 s, 4 s, 16 s) on 5xx/timeouts, none on 4xx; then dead-letter + in-app admin alert.
- Kill switch per installation; payload minimization by template-declared fields.

## Tests (`make test-contract`)

The channel contract suite must pass for `<key>`:
schema export; secret fields write-only; egress enforcement (including a destination that re-resolves to `127.0.0.1`);
retries on 5xx and timeouts; no retry on 4xx; idempotency; personal-data filtering; health.
Add unit tests for payload mapping in the same `test_<key>.py` (path must contain `<key>` for the review gate).

## Docs

`docs/guides/channels/<key>.md`: what you will do, prerequisites, numbered setup steps with the destination's side
(screenshots without real personal data), what data is sent, how to check it worked, what to do if it fails.
`CHANGELOG.md` under Unreleased.

## Ship

Commit scope `channel-<key>`, e.g. `feat(channel-slack): add slack incoming webhook channel`.
If the change touches `backend/app/channels/base.py`, run the `security-reviewer` agent (security path).
