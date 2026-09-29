<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# ADR-0011: Backend-for-Frontend (BFF) HttpOnly Refresh-Cookie Authentication

- **Status:** Accepted
- **Date:** 2026-09-23
- **Deciders:** Lead Architect, Security Team
- **Revisions / Supersedes:**
  - Revised 2026-09-29 (Decision 51): All server-side credentials and secrets live in OpenBao in production; file/env secrets used only for local development and CI; the browser and mobile clients hold zero credentials.
  - Revised 2026-09-29 (Decision 52): Multi-organization identity in Zitadel. One Zitadel organization per AssetFlow organization, sharing the AssetFlow project through project grants; active organization context is extracted from `urn:zitadel:iam:user:resourceowner:id`; Zitadel and OpenBao configured as code (OpenTofu) prior to provider boot.

---

## 1. Context and Problem Statement

Storing JWT access tokens and refresh tokens in browser storage (`localStorage` or `sessionStorage`) exposes user sessions to immediate exfiltration via Cross-Site Scripting (XSS) attacks. Legacy TMMS suffered from this vulnerability. Furthermore, in enterprise multi-tenant deployments, users belonging to different organizations must authenticate against a unified identity gateway without leaking credentials or granting cross-tenant access.

---

## 2. Decision Outcome

1. **BFF Refresh-Cookie Architecture**:
   - The browser holds short-lived access tokens strictly in memory (JavaScript heap).
   - The refresh token is issued as an encrypted, `HttpOnly`, `Secure`, `SameSite=Lax` cookie handled exclusively by the API backend. The browser runtime has zero programmatic access to the refresh token.
   - The API rotates the refresh token on every renewal cycle (`/api/v1/auth/refresh`), invalidating previously issued cookies.

2. **Zero Credentials in Browser / Mobile Clients (Decision 51)**:
   - All server-side credentials, client secrets, database passwords, and encryption keys are stored in OpenBao in production installations.
   - Clients hold no credentials, signing secrets, or master tokens.

3. **Multi-Organization Identity Federation (Decision 52)**:
   - Zitadel is the official OIDC preset. Each AssetFlow organization maps to a dedicated Zitadel organization, sharing the core AssetFlow project through project grants.
   - The user's active organization ID is derived deterministically from the Zitadel token claim `urn:zitadel:iam:user:resourceowner:id`.
   - Infrastructure setup (Zitadel projects, roles, OpenBao policies, AppRole credentials) is managed entirely as code (OpenTofu).

---

## 3. Consequences

### Positive & Negative Impact
- Good: Complete immunity against token exfiltration via client-side script injection (XSS).
- Good: Enforces strict tenant boundary at authentication: users authenticate into their specific organization context without cross-tenant elevation.
- Good: Adheres to zero-credential client principles (§B11.2, Decision 51).
- Cost: Requires dedicated `/api/v1/auth/refresh` endpoint and CSRF protections for cookie-based state changes.
- Cost: Requires OpenTofu automation scripts for provisioning Zitadel organizations and OpenBao AppRoles.

---

## 4. Alternatives Considered

- `localStorage` / `sessionStorage` token storage: Rejected due to fatal vulnerability to XSS token theft.
- Pure server-side session cookies (Redis session store): Rejected because it eliminates stateless API benefits and complicates native mobile clients.
- Single global Zitadel organization with role prefixes: Rejected because multi-organization Zitadel provides superior data isolation, compliance boundaries, and independent IdP federation per tenant.

---

## 5. References

- Master Plan §B3 (D11), §B2.1, §B5.5, §B11.2, §B11.4, §C5.5.
- Decisions Log §B17.1: Decision 51 (Credentials in OpenBao), Decision 52 (Multi-organization identity in Zitadel).
