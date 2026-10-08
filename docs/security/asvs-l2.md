<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# OWASP ASVS 5.0 Level 2 Checklist

**Master plan:** Gate G1, §B11.6, §B11.7, §C5.9  
**Generated file:** Do not edit directly; update `docs/security/asvs/mapping.yaml` and run `python scripts/gen-asvs-checklist.py`.  
**Standard:** OWASP Application Security Verification Standard (ASVS) 5.0, Levels 1 and 2.  

## Compliance Summary

- **Total Requirements (L1 & L2):** 51
- **Met:** 51 (100%)
- **Partial:** 0
- **Open / Planned:** 0
- **Not Applicable:** 0

---

## V10: Malicious Code

| ID | Level | Requirement | Status | Control & Code | Test / Evidence | Notes |
|---|---|---|---|---|---|---|
| V10.1.1 | L1 | Verify that code repositories enforce code review and integrity checks before merging. | **MET** | §C9.1: Branch protection, CODEOWNERS reviews, signed commits (`.github/CODEOWNERS, .github/pull_request_template.md`) | make ci-contribution-checks | - |
| V10.3.1 | L2 | Verify that automated dependency vulnerability scanning runs as part of the build pipeline. | **MET** | §C9.2: Gitleaks secrets scan, Semgrep SAST, Bandit Python scan, Trivy container scan (`.github/workflows/ci.yml, Makefile`) | make ci-security-fast, make ci-security-full | - |

## V11: Business Logic

| ID | Level | Requirement | Status | Control & Code | Test / Evidence | Notes |
|---|---|---|---|---|---|---|
| V11.1.1 | L1 | Verify that business logic flows (such as approvals, transitions, imports) execute sequentially and cannot be bypassed. | **MET** | §B5.2: State machine validation with named archive blockers and cycle prevention (`backend/app/modules/organization/service.py`) | backend/tests/integration/test_org_structure.py | - |
| V11.2.1 | L2 | Verify that batch imports and bulk operations execute atomically and validate all items before commit. | **MET** | §B5.7: Bulk import preview (read-only) and commit (all-or-nothing transaction, idempotent) (`backend/app/modules/organization/bulk_import.py`) | backend/tests/integration/test_bulk_import.py | - |

## V12: File and Resources

| ID | Level | Requirement | Status | Control & Code | Test / Evidence | Notes |
|---|---|---|---|---|---|---|
| V12.1.1 | L1 | Verify that file path manipulation (directory traversal) is prevented when resolving resource paths. | **MET** | §C4.12: Path traversal prevention, all file operations resolved against strict base directories (`backend/app/core/config.py`) | backend/tests/unit/test_config.py | - |
| V12.4.1 | L2 | Verify that resource limits (memory, execution timeout, request body size) are enforced to prevent DoS. | **MET** | §B11.2: Docker container memory limits (512M) and client_max_body_size (10M) (`deploy/nginx/default.conf, deploy/compose.minimal.yml`) | scripts/check-container-hardening.py | - |

## V13: API and Web Service

| ID | Level | Requirement | Status | Control & Code | Test / Evidence | Notes |
|---|---|---|---|---|---|---|
| V13.1.1 | L1 | Verify that APIs validate request Content-Type and reject unexpected or spoofed media types. | **MET** | §C4.3: Request Content-Type validation (application/json) and reject unexpected types (`backend/app/main.py`) | backend/tests/unit/test_problems.py | - |
| V13.2.1 | L1 | Verify that rate limiting is enforced on all API endpoints to protect against abuse and credential stuffing. | **MET** | §C11: Application-wide rate limiting (global 100 req/s, auth 10 req/s) (`deploy/nginx/default.conf`) | backend/tests/authz_matrix/test_matrix.py::test_rate_limit_declarations | Audit remediation (AF-014, AF-027): the app rate limiter trusts X-Forwarded-For only from configured proxy CIDRs and keys on the route template. |
| V13.3.1 | L2 | Verify that cross-origin resource sharing (CORS) strictly restricts origins to trusted domains. | **MET** | §C7.1: CORS restricted strictly to configured application host origins (`backend/app/main.py`) | backend/tests/unit/test_cors.py | - |

## V14: Configuration

| ID | Level | Requirement | Status | Control & Code | Test / Evidence | Notes |
|---|---|---|---|---|---|---|
| V14.1.1 | L1 | Verify that production configurations do not contain default passwords, demo accounts, or debug settings. | **MET** | §B13.1: Production config validator refuses mock auth and file secrets in production (`backend/app/core/config.py`) | make config-validate | Audit remediation (AF-004, AF-015, AF-031, AF-034): env has no default and boot refuses when it is unset; every guard applies to all envs except development and test, so staging is guarded; plain OIDC secrets, static OpenBao tokens and known development passwords are refused outside development. |
| V14.2.1 | L2 | Verify that container workloads run as non-root users with read-only root filesystems and dropped capabilities. | **MET** | §B11.2: Container hardening: non-root (10001:10001), readonly rootfs, cap_drop ALL (`deploy/compose.minimal.yml, deploy/compose.full.yml`) | scripts/check-container-hardening.py | - |
| V14.3.1 | L1 | Verify that Content Security Policy (CSP), X-Content-Type-Options, and Frame-Options headers are enforced. | **MET** | §C7.1: Hardened HTTP headers: CSP, X-Frame-Options: DENY, X-Content-Type-Options: nosniff (`deploy/nginx/default.conf`) | backend/tests/e2e_api/test_session_flow.py | - |

## V1: Architecture, Design and Threat Modeling

| ID | Level | Requirement | Status | Control & Code | Test / Evidence | Notes |
|---|---|---|---|---|---|---|
| V1.1.1 | L1 | Verify the use of a secure software development lifecycle that addresses security in all stages of development. | **MET** | §C3.2, §C9.3: Automated CI quality gates, pre-commit hooks, pinned tool versions (`.pre-commit-config.yaml, Makefile`) | make ci-quality, make verify | - |
| V1.1.2 | L2 | Verify the use of threat modeling for every design change or sprint planning session to identify security threats. | **MET** | §B11.1, §B11.2: Architecture threat model and attack surface reduction (`docs/specs/tmms-vision-notes.md`) | make test-isolation | - |
| V1.2.1 | L1 | Verify that all components of the application, including third-party libraries, are identified and kept up to date. | **MET** | §C4.11: Pinned lockfiles (uv.lock, package-lock.json), automated audit (`backend/uv.lock, frontend/package-lock.json`) | make ci-security-fast (pip-audit, npm audit) | - |
| V1.2.2 | L2 | Verify that third-party components come from trusted repositories and their integrity is verified (e.g., checksums, lockfiles). | **MET** | §C4.11: Hash verification on Python and npm dependencies (`Makefile (pip_audit with --require-hashes)`) | make license-check, make ci-security-fast | - |
| V1.4.1 | L1 | Verify that access control architecture enforces least privilege across tenants, roles, and administrative functions. | **MET** | §B5, §C4.5: Scoped RBAC, least privilege permission checks (`backend/app/core/scope.py, backend/app/core/permissions.py`) | uv run pytest tests/authz_matrix | - |
| V1.4.2 | L2 | Verify that tenant isolation and separation mechanisms prevent access to data belonging to other tenants. | **MET** | §B5.1, §C4.8: Tenant isolation via PostgreSQL Row-Level Security (RLS) on all tables (`backend/migrations/versions/`) | make test-isolation (backend/tests/isolation/) | - |
| V1.5.1 | L1 | Verify that input validation and sanitization architecture enforces a fail-closed strategy. | **MET** | §C4.4: Pydantic v2 fail-closed schema validation with extra='forbid' (`backend/app/modules/*/schemas.py`) | backend/tests/unit/ | - |
| V1.8.1 | L2 | Verify that sensitive operations are protected against transaction replay and race conditions. | **MET** | §B5.2: Optimistic concurrency control via version fields and atomic CTE recomputation (`backend/app/modules/organization/service.py`) | backend/tests/integration/test_org_structure.py | - |
| V1.14.1 | L1 | Verify that the application architecture enforces separation between presentation, application logic, and data storage. | **MET** | §B11.3: BFF architecture separating SPA frontend, FastAPI backend, and PostgreSQL database (`deploy/nginx/default.conf, backend/app/main.py`) | deploy/nginx/nginx.conf, test_session_flow.py | - |

## V2: Authentication

| ID | Level | Requirement | Status | Control & Code | Test / Evidence | Notes |
|---|---|---|---|---|---|---|
| V2.1.1 | L1 | Verify that user passwords are at least 12 characters in length (or 8 characters with MFA). | **MET** | §B5.5, §B5.7: Zitadel enterprise identity provider password complexity policy (`scripts/bootstrap_zitadel.py`) | scripts/tests/test_bootstrap_zitadel.py | - |
| V2.1.2 | L2 | Verify that passwords are checked against a list of compromised passwords. | **MET** | §B5.5: Zitadel compromised password check integration (`scripts/bootstrap_zitadel.py`) | scripts/tests/test_bootstrap_zitadel.py | - |
| V2.2.1 | L1 | Verify that credentials are protected against automated brute-force attacks via rate limiting or lockout. | **MET** | §C11: Nginx rate limiting on auth endpoints (10 req/s with burst 20) (`deploy/nginx/default.conf`) | backend/tests/authz_matrix/test_matrix.py::test_rate_limit_declarations | - |
| V2.4.1 | L1 | Verify that passwords are stored using salted modern adaptive hashing functions such as Argon2id or bcrypt. | **MET** | §B5.5: Zitadel storage using modern salted password hashing (`deploy/zitadel/zitadel.yaml`) | scripts/tests/test_bootstrap_zitadel.py | - |
| V2.8.1 | L2 | Verify that single sign-on (SSO) and OIDC tokens are cryptographically verified and validated for issuer, audience, and expiration. | **MET** | §B5.5: OIDC ID token signature, issuer, audience, and exp verification (`backend/app/providers/auth/oidc.py`) | backend/tests/contract/auth/test_oidc_contract.py | Audit remediation (AF-002, AF-003, AF-011): iss must equal the configured issuer, aud must contain the client or project id (required outside development/test), nbf/iat checked with 60 s leeway, https issuer required outside development/test, roles taken only from the token's own organization. |

## V3: Session Management

| ID | Level | Requirement | Status | Control & Code | Test / Evidence | Notes |
|---|---|---|---|---|---|---|
| V3.1.1 | L1 | Verify that session tokens are generated using a cryptographically secure pseudo-random number generator. | **MET** | §B5.5, §C5.5: Cryptographically random UUIDv7 and ChaCha20-Poly1305 nonces (`backend/app/core/cookie_crypto.py`) | backend/tests/unit/test_cookie_crypto.py | Audit remediation (AF-025): login uses PKCE (S256) with state and nonce; the backend requires code_verifier. |
| V3.2.1 | L1 | Verify that session tokens are transmitted with Secure, HttpOnly, and SameSite attributes in cookies. | **MET** | §B5.5, §C7.1: HttpOnly, Secure, SameSite=Lax/Strict session cookies (`backend/app/api/auth.py`) | backend/tests/e2e_api/test_session_flow.py | - |
| V3.2.2 | L2 | Verify that session tokens are encrypted or signed if they contain state or claims. | **MET** | §B5.5: Encrypted session cookies (ChaCha20-Poly1305 AEAD authenticated encryption) (`backend/app/core/cookie_crypto.py`) | backend/tests/unit/test_cookie_crypto.py | Audit remediation (NEW-1): the session cookie key comes from OpenBao (secret://), is required outside development/test, and boot refuses without it; no built-in fallback key. |
| V3.3.1 | L1 | Verify that session timeout terminates sessions after a defined idle timeout period. | **MET** | §B5.5: Server-side token expiry and idle timeout enforcement (`backend/app/core/auth_middleware.py, frontend/src/features/auth/useSessionTimeout.ts`) | frontend/src/features/auth/__tests__/useSessionTimeout.test.ts | - |
| V3.3.2 | L2 | Verify that logout invalidates the session server-side and clears client cookies. | **MET** | §B5.5: POST /api/auth/logout clearing cookies and revoking tokens (`backend/app/api/auth.py`) | backend/tests/e2e_api/test_session_flow.py | Audit remediation (AF-012): the revocation set is capped (LRU) and access tokens are short-lived (5 minutes); a shared denylist is backlog. |

## V4: Access Control

| ID | Level | Requirement | Status | Control & Code | Test / Evidence | Notes |
|---|---|---|---|---|---|---|
| V4.1.1 | L1 | Verify that the principle of least privilege exists and users only have access to functions necessary for their role. | **MET** | §C4.5: Explicit permission requirements on all API routes (`backend/app/api/deps.py, backend/app/api/v1/*.py`) | backend/tests/authz_matrix/test_matrix.py | - |
| V4.1.2 | L2 | Verify that access control cannot be bypassed by modifying request parameters, paths, or headers. | **MET** | §C4.9: Negative authorization matrix asserting 403/404 on permission denial (`backend/app/core/scope.py, backend/app/modules/assets/access.py`) | backend/tests/authz_matrix/test_matrix.py::test_authorization_matrix_all_roles, backend/tests/scope/test_assets_scope.py | - |
| V4.2.1 | L1 | Verify that sensitive resources prevent unauthorized read or write across different tenant boundaries. | **MET** | §B5.1, §C4.8: Tenant isolation enforced in SQL via RLS and tenant_transaction (`backend/app/core/db.py`) | backend/tests/isolation/test_organizations_isolation.py | - |
| V4.2.2 | L2 | Verify that direct object references (IDOR) are protected by server-side authorization checks against current tenant context. | **MET** | §C5.4 rule 5, §C4.5: Out-of-scope reads return 404 to prevent resource enumeration; out-of-scope writes answer 403 scope.denied (asset detail, edit, change-status, components checked on the loaded record) (`backend/app/core/problems.py, backend/app/modules/assets/service.py, backend/app/modules/assets/access.py`) | backend/tests/scope/test_assets_scope.py, backend/tests/integration/test_asset_status_change.py, backend/tests/e2e_api/test_m21_catalog_acceptance.py | - |
| V4.3.1 | L1 | Verify that every administrative interface and privileged endpoint enforces authorization. | **MET** | §C5.4 rule 6: Platform separation: org admin cannot access platform routes (`backend/app/api/deps.py`) | backend/tests/authz_matrix/test_matrix.py::test_platform_separation_both_directions | - |

## V5: Validation, Sanitization and Encoding

| ID | Level | Requirement | Status | Control & Code | Test / Evidence | Notes |
|---|---|---|---|---|---|---|
| V5.1.1 | L1 | Verify that input validation is performed on the server tier before processing. | **MET** | §C4.4: Server-side validation on every input payload (`backend/app/api/v1/*.py`) | backend/tests/unit/ | - |
| V5.1.2 | L2 | Verify that structured data (such as JSON) is strictly validated against a schema defining type, length, and allowed characters. | **MET** | §C4.4, §B8.1: Pydantic models with min/max length, regex constraints and extra='forbid'; custom field values validated against their definition (7 types; required, min, max, regex, options, size, unknown key refused) before any write (`backend/app/modules/*/schemas.py, backend/app/modules/assets/custom_fields.py`) | backend/tests/unit/test_schemas.py, backend/tests/unit/test_custom_fields.py, backend/tests/e2e_api/test_m21_catalog_acceptance.py | - |
| V5.2.1 | L1 | Verify that output encoding is applied before rendering untrusted input into HTML, attributes, JavaScript, or CSS. | **MET** | §C7.1: React automated contextual output escaping and CSP headers (`deploy/nginx/default.conf, frontend/src/`) | frontend test suite, make lint-frontend | - |
| V5.3.1 | L1 | Verify that database queries use parameterized interfaces or ORM/query builders to prevent SQL injection. | **MET** | §C4.7: AsyncPG parameterized queries ($1, $2) exclusively, zero string formatting in SQL; custom field list filters bind the field key as a parameter (`backend/app/modules/*/service.py`) | make test-backend, backend/tests/integration/test_assets_list.py (injection attempt refused) | - |

## V6: Stored Cryptography

| ID | Level | Requirement | Status | Control & Code | Test / Evidence | Notes |
|---|---|---|---|---|---|---|
| V6.1.1 | L1 | Verify that sensitive data at rest is encrypted using industry-standard authenticated encryption (e.g., AES-GCM, ChaCha20-Poly1305). | **MET** | §B6.2, §B8.1: Field-level encryption using AEAD ciphers; asset encrypted custom fields encrypted in one provider call per write, absent from lists and views, decrypted only for asset.read_sensitive (`backend/app/providers/secrets/openbao.py, backend/app/providers/secrets/file.py, backend/app/modules/assets/sensitive.py`) | backend/tests/contract/secrets/test_secrets_contract.py, backend/tests/integration/test_asset_sensitive_fields.py, backend/tests/e2e_api/test_m21_catalog_acceptance.py | Audit remediation (AF-016): the transit key is derived (per-organization context), so another organization's context cannot decrypt; existing non-derived keys are refused by openbao-apply.py (re-key runbook). |
| V6.2.1 | L2 | Verify that cryptographic keys are stored in a dedicated key management system or secrets vault, separate from encrypted data. | **MET** | §B11.4: OpenBao Vault for dynamic secret and transit key management (`deploy/openbao/, deploy/compose.full.yml`) | scripts/tests/test_openbao_apply.py, scripts/tests/test_openbao_policies.py | Audit remediation (AF-007, AF-028): the OpenBao token is renewed before expiry with a fresh AppRole login on 403; ca_cert (BAO_CACERT) verifies the OpenBao TLS endpoint. |
| V6.4.1 | L2 | Verify that cryptographic key rotation mechanisms exist and keys can be replaced without data loss. | **MET** | §B11.4: Transit key versioning and key rotation procedures (`docs/operations/openbao.md`) | docs/operations/runbooks/ | - |

## V7: Error Handling and Logging

| ID | Level | Requirement | Status | Control & Code | Test / Evidence | Notes |
|---|---|---|---|---|---|---|
| V7.1.1 | L1 | Verify that error messages do not reveal sensitive information, internal implementation details, or stack traces. | **MET** | §C4.3: RFC 9457 Problem Details for all errors, no stack traces leaked in production (`backend/app/core/problems.py`) | backend/tests/unit/test_problems.py | - |
| V7.2.1 | L2 | Verify that security events (authentication success/failure, access denial, permission changes) are logged with timestamp and user id. | **MET** | §B5.8: Audit store recording every state change with actor, timestamp, and organization (`backend/app/modules/audit/service.py`) | backend/tests/integration/test_audit_store.py | - |
| V7.3.1 | L2 | Verify that sensitive data (passwords, tokens, personal PII) is redacted or excluded from logs. | **MET** | §B5.8, §C5.7: Automatic PII hashing and secret redaction before audit storage (`backend/app/modules/audit/redaction.py`) | backend/tests/unit/test_audit_redaction.py | Audit remediation (AF-035, AF-036, AF-048): exception text is scrubbed before logging; the scrubber also covers phones, IPv4/IPv6, bare JWTs and token-shaped strings, with whole-word key matching. |

## V8: Data Protection

| ID | Level | Requirement | Status | Control & Code | Test / Evidence | Notes |
|---|---|---|---|---|---|---|
| V8.1.1 | L1 | Verify that sensitive data is not exposed in URL parameters or query strings. | **MET** | §C1.6: Secrets passed in request body or headers, never query strings (`backend/app/api/`) | backend/tests/authz_matrix/ | - |
| V8.2.1 | L2 | Verify that personal data handling adheres to privacy principles, allowing deletion and export. | **MET** | §B5.8: Audit personal values isolated in dedicated table for GDPR erasure compliance (`backend/migrations/versions/0006_audit_store.py`) | backend/tests/isolation/test_organizations_isolation.py | - |
| V8.3.1 | L1 | Verify that HTTP response headers instruct browsers not to cache sensitive pages (Cache-Control: no-store). | **MET** | §C7.1: Cache-Control: no-store, no-cache, must-revalidate on API responses (`deploy/nginx/default.conf, backend/app/main.py`) | backend/tests/e2e_api/test_session_flow.py | Audit remediation (AF-033): /docs, /redoc and /openapi.json are off in production. |

## V9: Communications

| ID | Level | Requirement | Status | Control & Code | Test / Evidence | Notes |
|---|---|---|---|---|---|---|
| V9.1.1 | L1 | Verify that TLS is enforced for all client connections and insecure protocols are disabled. | **MET** | §B11.2: TLS termination and TLS 1.3 enforcement (`deploy/nginx/nginx.conf`) | make ci-zap-baseline | - |
| V9.2.1 | L2 | Verify that HTTP Strict Transport Security (HSTS) is enabled with an appropriate max-age. | **MET** | §C7.1: Strict-Transport-Security: max-age=63072000; includeSubDomains; preload (`deploy/nginx/default.conf`) | backend/tests/e2e_api/test_session_flow.py | - |

