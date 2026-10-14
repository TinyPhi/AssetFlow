<!-- SPDX-FileCopyrightText: 2026 TinyPhi -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# Upgrade notes

Breaking changes that need an operator action, newest first. The upgrade procedure itself is
`make upgrade` (backup, migrations, restart).

## Audit hardening (pre-1.0 local changes)

### OpenBao policy and AppRole renamed

The Zitadel policy and AppRole are now `assetflow-zitadel` (were `zitadel`). Re-run
`make openbao-apply` (with `ISSUE_SECRET_IDS=1` to issue a new secret id) and restart the stack.
The role id and secret id are now read from `deploy/.secrets/assetflow-zitadel/`; the old
`deploy/.secrets/zitadel/` directory is no longer used and can be deleted after the upgrade.

### Zitadel TLS mode

`ZITADEL_TLS_MODE` now defaults to `external` (TLS ends at the proxy in front of Zitadel). For plain
http on localhost set both `ZITADEL_EXTERNALSECURE=false` and `ZITADEL_TLS_MODE=disabled`. See
[Zitadel](zitadel.md).

### Required `ASSETFLOW_ENV` and `ASSETFLOW_AUTH_PROVIDER`

`config/assetflow.yaml` no longer has defaults for `env` and `providers.auth.type`: both
`ASSETFLOW_ENV` and `ASSETFLOW_AUTH_PROVIDER` must be set wherever the config loads, or boot fails.
`deploy/compose.minimal.yml` and the Makefile default to `development` and `mock`;
`deploy/compose.full.yml` sets `oidc` and defaults the environment to `production`. Custom
deployments, scripts and CI jobs must set both.

### Transit key must be derived

The field-encryption transit key must be a derived key. Existing installations re-key following
[Re-key the transit key as derived](runbooks/rekey-transit-derived.md) before upgrading.

### New configuration keys

- `session_cookie_key`: a `secret://<area>/<name>#<key>` reference, required outside development
  and test.
- `database.sslmode`: must be `verify-full` outside development and test.

### Telemetry scrubber is always active

`providers.telemetry.settings.scrub: false` is refused outside development and test: the config
validation rejects it and so does the otel provider (staging included).

### Outbox NOTIFY payload

The PostgreSQL NOTIFY payload is a wake-up signal only and carries no event data; consumers read
the outbox rows. Custom listeners must not parse the payload. The default
`providers.events.settings.poll_interval_seconds` is now 2.0 (was 1.0).

### Browser session

- The refresh call must send the `X-Requested-With` header (the web client is updated; custom
  clients must add it).
- Mock sign-in exists only in `development` and `test`; other environments refuse mock auth.
- Identity from request headers (trusted-header sign-in) is removed; identity comes only from the
  session.
