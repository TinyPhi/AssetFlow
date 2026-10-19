<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# Installation & Profiles Guide

AssetFlow supports two deployment profiles (§B11.2, §B13.1, decisions 51 and 52):

1. **Minimal Profile (`deploy/compose.minimal.yml`):**
   - Designed for local development, CI, testing, and rapid evaluation.
   - Uses PostgreSQL with row-level security, mock identity provider, in-memory event bus, and Mailpit for email.
   - Starts in seconds with zero external dependencies.

2. **Full Profile (`deploy/compose.full.yml`):**
   - Designed for production-grade, hardened deployments.
   - Uses OpenBao for dynamic secret storage and transit encryption, Zitadel for enterprise OIDC/SSO authentication, PostgreSQL with dedicated least-privilege roles, and Nginx reverse proxy with hardened security headers.

---

## Port Allocation (P2-13 Map)

To avoid collisions with other services running on the host machine, AssetFlow maps all published host ports **strictly above 9000**:

| Service | Port Variable | Default Host Port | Profile |
|---|---|---|---|
| Web Reverse Proxy (Nginx) | `WEB_PORT` | `18080` | Minimal |
| AssetFlow API | `API_HOST_PORT` | `18080` | Full |
| PostgreSQL Database | `DATABASE_PORT` / `POSTGRES_HOST_PORT` | `15432` | Minimal / Full |
| Zitadel (Auth / Console) | `ZITADEL_EXTERNALPORT` | `19081` | Full, Identity |
| OpenBao Secrets Vault | `OPENBAO_HOST_PORT` | `19200` | Full |
| Mailpit SMTP / Web UI | `MAILPIT_SMTP_PORT` / `MAILPIT_WEB_PORT` | `11025` / `18025` | Minimal |

Any port can be customized by specifying the corresponding variable in your shell or in `.env.local`.

---

## Secrets Management (§C5.5)

In local development, secrets are managed under the `.secrets/` directory (ignored by git):
- `database/app/password`
- `database/migrator/password`
- `database/worker/password`
- `database/readonly/password`
- `auth/cookie_key`
- `crypto/field_key`

Permissions are automatically set to `chmod 600`. Existing secret files are never overwritten on subsequent runs.

In production (Full Profile), secrets are never stored on disk. Instead:
- Dynamic AppRole credentials (`role_id` and `secret_id`) are injected.
- Database passwords and tokens are rendered directly into volatile in-memory `tmpfs` mounts by OpenBao agent sidecars.

---

## Executing Bootstrap

### Minimal Profile:
```bash
scripts/bootstrap.sh --profile minimal
```

### Full Profile:
```bash
# Set your operator token for OpenBao
export BAO_TOKEN="<operator-token>"

scripts/bootstrap.sh --profile full
```

### Options:
- `--profile minimal|full`: Select target profile (default: `minimal`).
- `--dry-run`: Inspect actions without altering containers or disk state.
- `--reset`: Confirm and clean up existing volumes before starting.
- `--no-demo`: Skip seeding default demo organizations and initial accounts.
