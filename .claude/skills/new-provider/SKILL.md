---
name: new-provider
description: Scaffold a new AssetFlow provider implementation (auth, secrets, telemetry, events) behind its pillar interface, with the shared contract suite, following §B6.1-B6.2. Use for "new provider", "add a secrets/auth/telemetry/event bus backend", "support Keycloak/Vault/Redis", "provider-<name>".
---

# New provider

Pillars and interfaces live in `backend/app/providers/<pillar>/base.py` (`INTERFACE_VERSION = "1.0"`):
`AuthProvider` (verify_token, discovery, exchange_code, refresh, revoke), `SecretsProvider` (get, get_map, encrypt, decrypt),
`TelemetryProvider` (init, tracer, meter, logger; scrubber always on), `EventBusProvider` (publish, subscribe; at-least-once).
A new pillar or an interface change is an ADR decision; stop and write `docs/tracker/BLOCKERS.md`.

## Files

- `backend/app/providers/<pillar>/<name>.py` — the implementation (SPDX header, one-line docstrings on public functions).
- Register it in `backend/app/providers/registry.py` (built-in) or document the entry point
  `assetflow.providers.<pillar> = <name> = <pkg>:<Class>` for third-party packages.
- Config: `providers.<pillar>.type: <name>` plus a Pydantic settings model with descriptions and defaults;
  secrets only as `secret://<area>/<name>#<key>` references, never default values. `make config-validate`.
- `backend/tests/contract/<pillar>/test_<name>.py` — register with `@contract_target("<name>")` so the shared suite runs.
- `backend/tests/contract/<pillar>/fixtures/<name>/` — recorded HTTP (respx); PRs make no network calls.
- `docs/guides/writing-a-provider.md` section or `docs/operations/` page for setup; `docs/operations/secrets.md` for new secrets.

## Rules (§B6.1)

1. Config alone selects the provider; no code change to switch.
2. `health()` implemented and meaningful (shown at `/api/health/providers`).
3. Receives typed values and `organization_id`, never raw request objects.
4. Every outbound call: timeout, bounded retries with backoff, circuit breaker (open after 5 failures, half-open after 30 s).
   Behavior while open follows §B6.1 rule 9 (auth -> 503 `platform.auth_unavailable` for sign-in/refresh only;
   secrets -> cached until TTL then 503 `platform.secrets_unavailable`).
5. Production boot guards stay: refuse `auth.type=mock`, dev-mode OpenBao, disabled scrubbing, known default DB password,
   `file` secrets provider in production.
6. Vendor SDKs only inside the provider; nothing else imports them. New dependency: why, license on the allowlist, health,
   locked in `uv.lock` (§C4.11), stated in the PR.
7. Auth: PyJWT only; check `iss`, `aud`, `exp`, `nbf`, organization claim; reject unknown organizations; refresh JWKS on unknown `kid`.
8. Secrets: AppRole secret id from a file; values held in memory, renewed on TTL; never logged, never in env vars or images.

## Tests

- `make test-contract` — the pillar's contract suite passes for the new target (required to merge).
- Unit tests for parsing/mapping logic (`backend/tests/unit/providers/test_<name>.py`).
- Circuit-breaker and timeout behavior with recorded fixtures.
- `make test-providers-live` against a pinned real container when the provider claims "supported" status (§B6.1 rule 10).

## Security-path notes

`backend/app/providers/auth/` and `backend/app/providers/secrets/` are security paths: run the `security-reviewer` agent
and `af.py security set`. Commit scope `provider-<name>`.
