<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# Audit remediation (2026-10)

What the security audit fixes change in behaviour. Finding IDs (AF-nnn, NEW-n) are those of the
audit remediation plan. ASVS rows are in the [generated checklist](asvs-l2.md).

## Sign-in and tokens

- **OIDC checks (AF-002, AF-011).** `iss` must equal the configured issuer; `aud` must contain the
  client or project id (required outside `development` and `test`); `nbf` and `iat` are checked with
  60 s leeway. Roles are taken only from the token's own organization.
- **Issuer over https (AF-003).** An `https://` issuer is required outside `development`/`test`,
  the discovery `issuer` must equal the configured one, and there is no silent discovery fallback
  outside development.
- **PKCE (AF-025).** The SPA uses PKCE (S256) with `state` and `nonce`; the backend requires
  `code_verifier` and checks `state` and `nonce`.
- **Session cookie key (NEW-1).** The key comes from OpenBao (`secret://`), is required outside
  `development`/`test`, and boot refuses without it. Session exchange fails closed: no principal
  gives 401 and no cookie (NEW-2).
- **Token lifetime and revocation (AF-012).** Run access tokens at a short lifetime (5 minutes). The
  revocation set is capped (LRU). A shared denylist is on the backlog.

## Boot guards (AF-004, AF-015, AF-031, AF-034)

`env` has no default: boot refuses when it is unset. Every guard applies to all environments except
`development` and `test`, so `staging` is guarded (for example mock auth is refused there). Outside
development, a plain OIDC `client_secret`, an OpenBao static token and known development passwords
are refused, and `database.sslmode` must be `verify-full` in production.

## Rate limiting (AF-014, AF-027)

The app rate limiter trusts `X-Forwarded-For` only from configured proxy CIDRs and takes the
rightmost untrusted hop; nginx sets `X-Forwarded-For $remote_addr`. The key uses the route template,
not the concrete path.

## OpenBao (AF-007, AF-016, AF-028)

- The token is renewed (`renew-self`) before expiry; a 403 triggers a fresh AppRole login.
- `ca_cert` (read from `BAO_CACERT`) is used to verify the OpenBao TLS endpoint.
- The transit key is created `derived: true`, so one organization's context cannot decrypt another's
  data. An existing non-derived key is refused; recreate it with the
  [re-key runbook](../operations/runbooks/rekey-transit-derived.md). Local test data encrypted with
  the old key becomes unreadable.

## Logging (AF-035, AF-036, AF-048)

Exception text is scrubbed before logging and a root logging filter applies. The scrubber also covers
phone numbers, IPv4/IPv6 addresses, bare JWTs and token-shaped strings, and matches keys as whole
words.

## API surface (AF-033, NEW-3)

`/docs`, `/redoc` and `/openapi.json` are off in production. The mock authorize routes are mounted
only when the auth provider is `mock` and the environment is `development` or `test`.

## Platform permissions (AF-045)

Platform permissions are config/CLI-only; they are not grantable through the API or the UI. See
[roles and scopes](../guides/admin/roles-and-scopes.md).
