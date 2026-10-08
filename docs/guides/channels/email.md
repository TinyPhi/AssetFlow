<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# Email channel

The `email` channel sends an HTML and plain-text message over SMTP for every notification an
automation rule routes to it (§B6.3). The SMTP relay belongs to the installation; each organization
sets only who the mail comes from.

## 1. Set up the relay (operator)

In `config/assetflow.yaml`:

```yaml
notifications:
  channels:
    email:
      enabled: true
      host: smtp.example.org
      port: 587
      security: starttls          # starttls (port 587), tls (implicit, port 465) or none
      username: relay-user
      password: secret://smtp/relay#password   # a reference, never the password itself
      default_from: notifications@example.org
      timeout_seconds: 10
```

- `password` must be a `secret://` reference; the secrets provider (OpenBao in production) holds the
  value, and only the worker's channel runtime reads it.
- `security: none` (plain SMTP) and `allow_private_addresses: true` exist for a local mail catcher
  such as Mailpit in development. **Production boot refuses both.**
- With `starttls` or `tls` the relay's certificate is verified; there is no switch to turn that off.
- The relay's host name is the one host the channel may reach. It must resolve to public addresses
  only (every address is checked, and the connection goes to the address that passed the check).
- Development uses Mailpit through `ASSETFLOW_SMTP_HOST` and `ASSETFLOW_SMTP_PORT`
  (defaults `mailpit` and `1025`); open its inbox at the host port mapped to its web UI.

## 2. Install the channel (organization admin)

`POST /api/v1/notification-channels/installations` with:

```json
{
  "channel_key": "email",
  "settings": {"from_address": "alerts@example.org", "from_name": "Example Alerts", "reply_to": "help@example.org"},
  "allow_personal_data": false
}
```

All three settings are optional; without `from_address` the platform's `default_from` is used. There
are no secrets to enter: the relay credentials are installation-wide.

## 3. What is sent

- One `multipart/alternative` message: the `.txt` template as plain text and the `.html` template as
  HTML (HTML is auto-escaped; plain text is not).
- The subject is the template's `subject` line, otherwise its plain text.
- `Message-ID` is `<idempotency key@sender domain>`, so a delivery that is sent twice (the one
  case is a worker dying between send and recording) carries the same id and a receiver can drop
  the duplicate.
- Only the event fields a template declares are used. Fields it marks `personal_fields` (names and
  the like) are left out unless the installation has `allow_personal_data: true`.
- Templates live in `config/templates/<language>/`; a missing translation falls back to `en`. Members
  have no language setting yet, so mail is sent in `en`.

## 4. What is never stored or logged

The recipient's address is read from the member record at send time and is held in memory for that
one send. It is not written to a log, a trace, a metric tag or the delivery log: a delivery's
`target` is the member id. SMTP replies are reduced to a code (`smtp_550`), never the server's text.

## 5. Failures

| Outcome | Result |
| --- | --- |
| SMTP `4yz` reply, timeout, lost connection | retried (3 attempts, 1 s then 4 s apart) |
| SMTP `5yz` reply, rejected certificate, refused address | not retried: dead-lettered, admins are told |
| Member left, suspended or not yet active | skipped, nothing is sent |

See the [SMTP outage runbook](../../operations/runbooks/smtp-outage.md) and
[dead-letter handling](../../operations/runbooks/dlq-handling.md).

## 6. SPF, DKIM and DMARC

Mail from your own domain needs SPF, DKIM and DMARC records for the relay you use; your relay
provider documents the exact records. AssetFlow does not sign mail itself.
