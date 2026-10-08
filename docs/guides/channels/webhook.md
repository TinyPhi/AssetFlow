<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# Webhook channel

The `webhook` channel sends a signed HTTPS `POST` to a URL you choose whenever one of the events you
listed happens (§B6.3). Only the fields you map are sent.

## 1. Install it (organization admin)

`POST /api/v1/notification-channels/installations`:

```json
{
  "channel_key": "webhook",
  "settings": {
    "url": "https://hooks.example.org/assetflow",
    "events": ["team_member.added"],
    "field_mapping": {"team.id": "team_id", "team.role": "team_role", "member": "member_id"},
    "include_personal_data": false
  },
  "secrets": {"signing_secret": "<at least 16 characters, kept by you>"}
}
```

- `url` must be `https://`, with a host and no user name, password or fragment. Its host becomes the
  only host this installation may call; it must resolve to public addresses only (private, loopback
  and link-local addresses are refused, and so is following a redirect).
- `events` are event types AssetFlow knows. An event you did not list is never sent here.
- `field_mapping` maps a target path in your payload (dotted, for nesting) to a field of the event.
  A source field that one of the listed events does not carry is refused when you save, not when a
  request is sent. `event_type`, `event_id`, `occurred_at` and `organization_id` are always sent and
  cannot be mapped.
- `signing_secret` is write-only: the API only ever answers `{"set": true}`. Send a new value with
  `PATCH` (and the current `version`) to rotate it.
- Fields an event type marks as personal are sent only when `include_personal_data` is true **and**
  the installation's `allow_personal_data` is true. Both default to false.

## 2. The request

```
POST /assetflow HTTP/1.1
Content-Type: application/json
X-AssetFlow-Delivery-Id: <idempotency key, 64 hex characters>
X-AssetFlow-Timestamp: <Unix seconds>
X-AssetFlow-Signature: sha256=<hex>
```

The body is canonical JSON (sorted keys, no spaces, UTF-8), serialized once; those exact bytes are
signed and sent:

```json
{"event_id":"...","event_type":"team_member.added","member":"...","occurred_at":"2026-03-01T12:00:00+00:00","organization_id":"...","team":{"id":"...","role":"member"}}
```

The signature is `sha256=` followed by the hex HMAC-SHA256, keyed with your signing secret, of the
timestamp, a dot, and the raw body: `HMAC(secret, timestamp + "." + body)`.

## 3. Verify it (receiver)

Reject a request when the timestamp is more than **5 minutes** from your clock, or when the
signature does not match (compare in constant time). Use the raw body bytes, not a re-serialized
copy. Use `X-AssetFlow-Delivery-Id` to drop a duplicate: the same delivery is only ever sent again if
a worker died after sending and before recording it.

Python:

```python
import hashlib, hmac, time

def verify(secret: str, headers: dict[str, str], body: bytes) -> bool:
    timestamp = headers["X-AssetFlow-Timestamp"]
    if abs(time.time() - int(timestamp)) > 300:
        return False
    expected = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(headers["X-AssetFlow-Signature"], f"sha256={expected}")
```

Node.js:

```js
const crypto = require("node:crypto");

function verify(secret, headers, body /* Buffer */) {
  const timestamp = headers["x-assetflow-timestamp"];
  if (Math.abs(Date.now() / 1000 - Number(timestamp)) > 300) return false;
  const expected = crypto
    .createHmac("sha256", secret)
    .update(`${timestamp}.`)
    .update(body)
    .digest("hex");
  const given = Buffer.from(headers["x-assetflow-signature"]);
  const wanted = Buffer.from(`sha256=${expected}`);
  return given.length === wanted.length && crypto.timingSafeEqual(given, wanted);
}
```

## 4. Responses and retries

| Your answer | What AssetFlow does |
| --- | --- |
| `2xx` | delivered |
| `5xx`, a timeout, a connection error | retried: 3 attempts, 1 s then 4 s apart, then dead-lettered |
| any `4xx` (including `429`) or `3xx` | not retried: dead-lettered, organization admins are told |

Answer quickly (within 10 seconds) and do slow work afterwards. See
[dead-letter handling](../../operations/runbooks/dlq-handling.md) to send a dead-lettered delivery
again after you fixed the receiver.

## 5. What is never stored or logged

The signing secret lives only in the secrets provider; the database keeps a reference and the fact
that it is set. No request body, URL, header or server answer is written to a log or the delivery
log; a delivery's `target` is the member id and its `error_code` is a code such as `http_503`.
