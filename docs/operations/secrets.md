<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# Secrets: where each kind lives

In production every server-side credential lives in OpenBao; the database, the config file and the
images hold references only (decision 51). The `file` provider exists for development and CI and is
refused in production. See [OpenBao operations](openbao.md) for running it.

## Notification channel credentials

| Kind | Path | Written by | Read by |
| --- | --- | --- | --- |
| A channel installation's secrets (a webhook's signing secret) | `secret/assetflow/orgs/<organization_id>/channels/<channel_id>` | the API, when an admin installs or changes the channel | the worker's channel runtime, at send time |
| The SMTP relay's password | the `secret://` reference in `notifications.channels.email.password` (for example `secret://smtp/relay#password`) | the operator | the worker's channel runtime |

The `notification_channels` row keeps only the reference and the **names** of the secret fields that
have a value. It never keeps a secret, not even encrypted.

### Policies

- **`assetflow-api`** may `create`, `update`, `patch` and `delete` the channel path and may **not**
  `read` or `list` it, so an admin can save, rotate or remove a credential but nothing can read one
  back. This is the only path where the API role writes.
- **`assetflow-worker`** may `read` the channel path and may not write it. The runtime reads a
  credential for one send and drops it.
- No other role has any capability on the channel path.

`scripts/tests/test_openbao_policies.py` parses the real policy files and fails if any overlapping
stanza would let the API read or list a channel credential.

### Rotating

- A webhook signing secret: `PATCH` the installation with a new `signing_secret`. Tell the receiver
  first or accept a short window of rejected signatures; there is no dual-key period.
- The SMTP relay password: change it in OpenBao; the next send reads it. Nothing restarts.
- A suspected leak of a channel credential: disable the installation (the kill switch), rotate the
  credential at the destination, set the new value, enable it again.

## What is never logged

No log line, trace attribute, metric tag, audit diff or outbox payload contains a secret value, a
recipient address or a message body. Errors carry a code (`smtp_550`, `http_503`), not the server's
text.
