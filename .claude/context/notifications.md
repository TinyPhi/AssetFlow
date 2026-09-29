# Context: notifications

Orientation for `backend/app/channels/`, `modules/notifications/`, `workers/notification_sender.py`, `config/templates/` and the admin channel screens. Plan sections: D15, D17, §B6.3, §B7.2 (`notifications.channels`), §B7.3 (automations), §B9.3, §B11.1 (notifications row), §C1.6, §C6.7, §C8.4 (channel suite), §C8.6.

## What 1.0 ships (D15)

| Channel | Behaviour |
| --- | --- |
| `inapp` | `notifications` table (RLS per organization and member); bell + inbox polled every 30 s and on focus with `updated_since`; read/unread, mark all read, retention (180 days default) |
| `email` | SMTP with STARTTLS/TLS; Jinja HTML + text templates from `config/templates/<lang>/`, auto-escaped; per-organization sender |
| `webhook` | Signed HTTPS POST (HMAC-SHA256 over timestamp + body, delivery id); declarative field mapping; personal data off by default |

Later (1.x): Slack, Teams, Google Chat, WhatsApp, push. Each is one file implementing `NotificationChannel` plus contract tests.

## Flow

1. A service writes a domain event to the outbox in its transaction.
2. The dispatcher runs automation rules (from the domain template) -> recipients resolved **inside the organization context**: `holder`, `actor`, `assignee`, `assignee_team`, `team_lead`, `requester`, `role:<role>@<scope reference>`, `org_unit_manager`.
3. Member preferences filter per event type and channel (in-app always on for mandatory events such as custody acknowledgement).
4. The notification sender renders the template and calls the channel through the runtime.
5. Every attempt is written to `notification_deliveries`.

## `NotificationChannel` interface (`channels/base.py`, security path)

Each channel declares: key, settings schema (Pydantic `config_schema`, no secrets), secret fields (`SecretStr`), allowed hosts (`egress_hosts`), `send()`, `health()`.

## Channel runtime rules (§B6.3)

1. Connectors never read secrets. The runtime reads them from OpenBao (`secret/assetflow/orgs/<organization_id>/channels/<channel_id>`) and passes them in `ChannelContext` for one call; never logged.
2. Egress allowlist via `ctx.http` only: channel `egress_hosts` plus admin-added hosts for webhook-type channels. Re-checked on every call and retry; private, loopback and link-local blocked **after DNS resolution**; connect to the exact checked address.
3. Payload minimization: templates declare fields; email, phone, name only where the installation allows personal data.
4. Delivery log for every attempt: channel, target, status, latency, error, next retry.
5. Retries: 3 attempts, backoff 1 s, 4 s, 16 s; then dead-letter, in-app alert to organization admins, note on the record. Attempts while a circuit is open do not count.
6. Kill switch per channel installation.
7. Idempotency key per (event, recipient, channel): inbox dedupes on it, email uses it as `Message-ID`, webhook sends it as delivery id.
8. First-party in the repo; third-party via entry points with the same contract suite.

## Settings and secrets in the UI (D17)

- Schema published at `/api/v1/notification-channels/{key}/schema`; the admin form and a Zod validator are generated from it. No per-channel frontend code.
- The API validates again with Pydantic. Secret fields are write-only: stored encrypted, never returned, shown as "set / not set".

## Adding a channel (§C6.7, main first-contribution path)

1. `channel.yml` issue (destination, auth, egress hosts, personal data); wait for `accepted`.
2. `make new-channel name=<key>` scaffolds `backend/app/channels/<key>.py`, `backend/tests/contract/channels/test_<key>.py`, recorded fixtures, `docs/guides/channels/<key>.md`.
3. Implement `config_schema`, `egress_hosts`, `send()`, `health()` using only `ctx.http` and `ctx.credentials`.
4. Pass `make test-contract`: schema export, write-only secrets, egress enforcement (including a host that re-resolves to `127.0.0.1`), retries on 5xx/timeouts, no retry on 4xx, idempotency, personal-data filtering, health.
5. Add the display name to `en.json`; add scope `channel-<key>` to commitlint.

## Templates and keys

- Template key kebab-case = file name: `asset-assigned` -> `config/templates/en/asset-assigned.html`.
- Template tests include non-Latin sample text.
- Events include `asset.assigned`, `asset.returned`, `asset.warranty_expiring`, `work_request.created`, `work_request.triaged`, `work_order.created`, `work_order.dispatched`, `work_order.due_soon`, `work_order.overdue`, `work_order.sla_warning`, `work_order.sla_breached`, `work_order.completed`.

## Milestone

M1.5 done when one event produces an in-app notice, an email and a signed webhook, all logged, and a failing mail server leads to retries then an admin alert.
