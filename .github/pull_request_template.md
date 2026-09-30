<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

## 1. Summary

<!-- What changed and why? Reference relevant issues. -->
Closes #

## 2. Type of Change

- [ ] `type/bug` Bug fix
- [ ] `type/feature` New feature or functionality
- [ ] `type/provider` New or updated provider (OIDC, secrets, telemetry, events)
- [ ] `type/channel` New or updated notification channel
- [ ] `type/domain-config` Domain template update (`config/domains/*.yaml`)
- [ ] `type/docs` Documentation update
- [ ] `type/refactor` Code refactoring without behavior change
- [ ] `type/security` Security improvement or fix

## 3. Contributor Checklist

- [ ] My code adheres to the [Coding Guidelines](../CONTRIBUTING.md) and neutral domain vocabulary (no industry-specific terms in code).
- [ ] Tests have been added or updated, and coverage does not drop.
- [ ] **Tenancy & RLS**: Any new database tables have `organization_id NOT NULL`, `FORCE ROW LEVEL SECURITY`, four fail-closed policies, an `organization_id`-first index, and isolation tests. Views are `security_invoker`.
- [ ] **Route Security**: Any new route declares an explicit permission dependency via `ctx.scope.require(...)` or an explicit `public_route(rate_limit=...)`.
- [ ] **Database Migrations**: Includes forward and backward downgrade steps (`upgrade` and `downgrade`).
- [ ] **Config & Events**: Any new configuration keys or domain events are documented in `config/` or `docs/`.
- [ ] **Data Hygiene**: Zero secrets, API keys, credentials, or personal data (PII) in code, tests, fixtures, or logs.
- [ ] **Documentation**: Updated `CHANGELOG.md` and relevant guides in `docs/`.
- [ ] **Architecture**: Linked relevant ADR (`docs/decisions/`) or technical specification (`docs/specs/`) if applicable.
- [ ] **Contributor License Agreement**: I have read the [Contribution Terms](https://github.com/TinyPhi/AssetFlow/blob/main/CONTRIBUTING.md#1-contribution-terms) and signed the [Contributor Assignment Agreement](https://github.com/TinyPhi/AssetFlow/blob/main/CLA.md) (the CLA Assistant bot asks on your first PR).
- [ ] **Third-Party Work**: Any third-party work included in this PR is identified, with its source and license.

## 4. Security Notes

<!-- Detail tenancy/scope impact, new inputs, new outbound network calls, or write "None". -->
None

## 5. How to Verify

<!-- Detailed steps or commands to verify this change locally (e.g., make verify, specific test commands). -->
```bash
make verify
```
