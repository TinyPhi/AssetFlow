# Context: providers and secrets

Orientation for `backend/app/providers/`, `core/config*`, `deploy/bootstrap/`, and any code that needs a credential. Plan sections: D3, D11, D17, §B6.1, §B6.2, §B7.2, §B11.1 (secrets row), §B11.2, §B11.4, §B11.9, §C1.6 (secret reference), §C3.3, §C5.5, §C5.7.

## Four pillars, one default and one fallback each (D3, §B6.2)

| Pillar | Interface | Default | Fallback |
| --- | --- | --- | --- |
| Auth | `AuthProvider`: `verify_token`, `discovery`, `exchange_code`, `refresh`, `revoke` | `oidc` with the Zitadel preset | `mock` (dev/tests only) |
| Secrets | `SecretsProvider`: `get`, `get_map`, `encrypt`, `decrypt` | `openbao` (AppRole, KV v2, transit) | `file` (dev/CI only) |
| Telemetry | `TelemetryProvider`: `init`, `tracer`, `meter`, `logger`; scrubber always on | `otel` (OTLP) | `noop` |
| Events | `EventBusProvider`: `publish`, `subscribe` | `postgres` | `inmemory` (tests only) |

Layout: `providers/<pillar>/base.py` (interface, `INTERFACE_VERSION = "1.0"`) plus implementations; `providers/registry.py` resolves built-ins and entry points (`assetflow.providers.<pillar>`).

## Rules for every provider (§B6.1)

1. Config alone chooses it (`providers.<pillar>.type`).
2. Every implementation passes `tests/contract/<pillar>/` (recorded HTTP, `@contract_target`). `make test-providers-live` runs against real containers on demand.
3. `health()` feeds `/api/health/providers` and the admin screens.
4. Unconfigured pillar -> fallback plus a startup warning.
5. Production boot fails on `auth.type=mock`, missing cookie key, scrubbing disabled, OpenBao dev mode, known default DB password, and the `file` secrets provider.
6. Providers receive typed values and `organization_id`, never request objects.
7. Every outbound call: timeout, bounded retries with backoff, circuit breaker (open after 5 failures, half-open after 30 s). Open auth breaker -> sign-in/refresh/logout return `503 platform.auth_unavailable`; valid access tokens keep working via cached JWKS.
8. Only providers and channels import vendor SDKs; one JWT library (PyJWT).
9. Settings are Pydantic models published as JSON Schema (D17).
10. A new provider needs an ADR; the PR links it (contribution check).

## Secrets: OpenBao for everything server-side (§B11.4)

- **Production: every server credential lives in OpenBao** (DB passwords, SMTP, IdP client secret, channel secrets, field-encryption transit key). Both deployment profiles.
- Containers get only their AppRole login as a read-only mounted file. Never copy credentials into env vars, `.env` files or images.
- At boot, API and worker log in, read what they need into memory, renew and re-read on TTL (rotation needs no restart). Sealed or unreachable -> boot stops with `platform.secrets_unavailable`; at runtime -> `503 platform.secrets_unavailable` only for requests that need a secret.
- Policies: read-only on `secret/assetflow/*`; encrypt/decrypt on `transit/assetflow-fields`.
- Channel credentials: `secret/assetflow/orgs/<organization_id>/channels/<channel_id>`; the DB stores only the reference.
- `file` provider: generated, git-ignored values in `.secrets/` for local development and CI.
- Transit key and unseal material are backed up separately from the database, by two holders; restore keys before the database.

## References, not values (§B7.2, §C1.6)

- Config holds `secret://<area>/<name>#<key>` (e.g. `secret://database/app#url`) and `${ASSETFLOW_*}` only.
- New secret: add a reference, document it in `docs/operations/secrets.md`, never a default value.
- Env vars owned by AssetFlow start with `ASSETFLOW_`; tools keep their names (`BAO_ADDR`, `OTEL_EXPORTER_OTLP_ENDPOINT`). `os.environ` only in `core/config.py`.

## The browser holds no credentials (D11, §B11.2)

- Authorization code + PKCE through the BFF; public client, no secret.
- Refresh token encrypted (AES-GCM, key from `SecretsProvider`) inside an HttpOnly, Secure, `SameSite=Strict` cookie scoped to `/api/auth`, rotated on every use.
- Access token in memory, 5–15 min, Bearer header. Refresh requires an `Origin` check and `X-Requested-With: AssetFlow`.
- Machine integrations use IdP service users (client credentials); AssetFlow issues no long-lived API keys.

## Break-glass (D18, §B11.9)

`assetflow admin break-glass --organization <slug> --reason "<text>"`: local, max 4 h, one browser, no refresh, fully audited, all admins notified; disabled by `platform.break_glass: false`.

## Leak procedure (§C5.7)

Rotate first. Then check audit and IdP logs, remove in a new commit (no reliance on history rewrite), track privately, add a gitleaks rule.
