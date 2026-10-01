---
paths:
  - "backend/app/core/permissions*"
  - "backend/app/core/permissions/**"
  - "backend/app/core/db*"
  - "backend/app/core/db/**"
  - "backend/app/core/auth_middleware.py"
  - "backend/app/providers/auth/**"
  - "backend/app/providers/secrets/**"
  - "backend/app/channels/base.py"
  - "backend/app/modules/organization/**"
  - "backend/app/modules/assets/qr/public*"
  - "backend/app/modules/assets/qr/public*/**"
  - "backend/migrations/**"
  - "deploy/**"
  - ".github/workflows/**"
  - "scripts/check-*"
---

# Security rules (security-sensitive paths)

Source: plan §B11, §C5.1–§C5.9, §B12.1. These paths (§C5.8, mirrored in `.claude/loop.json` `security_paths`) always need:

1. the **security-reviewer** agent verdict recorded with `python .claude/hooks/af.py security set < security.json` (the commit gate refuses without it, and refuses on `block`);
2. the **second reviewer's** approval on the PR through CODEOWNERS (`@TinyPhi/assetflow-security`);
3. the line "self-reviewed against §C5.9" in the PR security notes.

`.github/workflows/` is also **off-limits** to the agent: stop and write `docs/tracker/BLOCKERS.md`.

## Principles (§C5.1)

- Deny by default: a route without a permission fails the authorization matrix; a table without RLS fails the migration lint; a list without a `ScopeFilter` fails a test.
- Defence in depth: RLS enforces the organization boundary in the database; the scope resolver enforces org unit / team / self in the application. Both are tested.
- Least privilege: separate DB roles (`assetflow_api`, `assetflow_worker`, `assetflow_migrator`); connectors get only their credentials and hosts.
- Every write, including admin and security actions, produces an audit event.
- Production boot refuses unsafe settings: `auth.type=mock`, missing cookie key, scrubbing off, OpenBao dev mode, default DB password, `file` secrets provider, `open` provisioning without `platform.allow_open_provisioning`.

## Tenancy and scope (§C5.4)

- Tenant data only through `ctx.db.transaction()` / `worker_context(organization_id)`, which call `set_config('app.organization_id', $1, true)`.
- Record-level: `ctx.scope.require(permission, record)` on the loaded record. List-level: `ScopeFilter`.
- Scope-denied reads return 404 (do not reveal existence).
- `*` in an organization never includes `platform.*`. Platform permissions come only from `platform.admins` config and are checked only with no organization context.
- A member can grant only a role whose every permission they hold at a scope covering the target.
- IdP role sync runs on login **and every token refresh**; `grants_changed` via `LISTEN/NOTIFY` clears caches at once; suspension is checked every request, uncached.
- Tokens for unknown organizations are rejected; an organization is never created from a token. `invite_only` links only on `email_verified=true` and exact case-normalized email match; never re-link by email.

## Secrets (§B11.4, §C5.5)

- **OpenBao holds every server-side credential in production** (DB passwords, SMTP, IdP client secret, channel secrets, field-encryption transit key). Containers get only an AppRole login as a read-only mounted file.
- The `file` provider is for local development and CI only, with generated, git-ignored values (`.secrets/`).
- Config holds only `secret://<area>/<name>#<key>` references or `${ASSETFLOW_*}`. Never a default secret value.
- Read secrets only through `SecretsProvider`. Never return them from the API (write-only, shown as "set / not set"), never log them.
- Channel credentials: `secret/assetflow/orgs/<organization_id>/channels/<channel_id>`; only the channel runtime reads them and passes them in `ChannelContext` for one call.
- **The browser holds no credentials**: HttpOnly `SameSite=Strict` refresh cookie scoped to `/api/auth`, encrypted with AES-GCM and rotated on use; access token in memory only; PKCE, no client secret.
- Suspected leak: rotate first (§C5.7), then investigate. Never paste a secret into an issue, PR or log.

## Outbound calls and inputs

- Outbound HTTP only through a provider or the channel runtime's allowlisted client (`ctx.http`): egress allowlist, re-checked on every call and retry; private, loopback and link-local addresses blocked **after DNS resolution**; connect to the exact checked address. Timeouts, bounded retries, circuit breaker.
- Webhooks: HTTPS only, HMAC-SHA256 over timestamp + body, delivery id for idempotency.
- Public scan/report: 128-bit capability tokens stored hashed, rotatable and revocable; never accept a tag alone; return only `public_scan_fields`; rate limits per IP and per token; text-only reports with a honeypot; tokens scrubbed from logs.
- Never use user input in SQL, file paths, URLs, templates or shell commands without validation. Automation conditions are structured YAML, never evaluated expressions (D8).
- Imports: size/row limits, MIME + magic bytes, `defusedxml`, zip-bomb guard, parse in the worker. Exports: prefix cells starting with `= + - @ TAB CR` with `'`. PDFs: auto-escaped templates; no remote or local-file resource loading (D16).

## Personal data (§C5.2, §B11.8)

- Names, emails, phones, IP addresses: never in logs, traces, metrics or `audit_events` (use `audit_personal_values`). Telemetry uses pseudonymous member ids.
- Sent to channels only when the installation allows personal data.

## CI/CD and deploy

- No `pull_request_target` with untrusted checkout; empty default `permissions`; actions pinned by SHA; runner pinned; no secrets in fork runs.
- Containers: non-root (UID 10001), read-only root fs, `cap_drop: [ALL]`, `no-new-privileges`, limits, healthchecks. Headers and CSP as in §C5.10.

## Review checklist (§C5.9)

- [ ] Every new route has a permission, or an explicit public marker with a rate limit.
- [ ] Reads and writes check scope on the loaded record.
- [ ] New tables and views meet §C4.8 (RLS, `FORCE`, policies, `security_invoker`).
- [ ] No unvalidated user input in SQL, paths, URLs, templates or shell.
- [ ] New outbound calls only through a provider or channel with an egress allowlist.
- [ ] No error message or timing difference reveals records in another scope or organization.
- [ ] No personal or sensitive data logged, traced, exported or sent without permission.
- [ ] Secrets read only through `SecretsProvider`, never returned by the API.
- [ ] New dependencies justified and license-allowlisted (§C4.11; no GPL/AGPL/static LGPL).
- [ ] A test fails without the security control.
- [ ] `docs/security/asvs-l2.md` updated for affected ASVS Level 2 requirements.
- [ ] Errors follow RFC 9457 without internal details.
