<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# ADR-0011: Backend-for-Frontend (BFF) HttpOnly Refresh-Cookie Authentication

- **Status:** Accepted
- **Date:** 2026-09-23
- **Deciders:** Lead Architect, Security Team
- **Revisions / Supersedes:** Reaffirmed in §B11.2, §C5.5, Decisions 51 & 52.

---

## 1. Context and Problem Statement

Storing JWT access tokens and refresh tokens in browser `localStorage` or `sessionStorage` exposes sessions to theft via Cross-Site Scripting (XSS) vulnerabilities. Legacy TMMS suffered from this exact vulnerability.

---

## 2. Decision Outcome

Implement a Backend-for-Frontend (BFF) authentication architecture. The browser holds short-lived access tokens strictly in memory. The refresh token is issued as an encrypted, `HttpOnly`, `Secure`, `SameSite=Lax` cookie handled exclusively by the API backend. The browser JavaScript runtime can never access the raw refresh token.

---

## 3. Consequences

### Positive & Negative Impact
- Good: Complete immunity against token exfiltration via client-side script injection (XSS).
- Good: Refresh token rotation ensures that stolen cookies cannot be replayed after a refresh cycle.
- Cost: Requires dedicated `/api/v1/auth/refresh` endpoint and CSRF protections for cookie-based state changes.

---

## 4. Alternatives Considered

- `localStorage` / `sessionStorage` token storage: Rejected due to fatal vulnerability to XSS token theft.
- Pure server-side session cookies (Redis session store): Rejected because it eliminates stateless API benefits and complicates native mobile clients.

---

## 5. References

- Master Plan §B3 (D11), §B2.1, §B11.2, §C5.5.
