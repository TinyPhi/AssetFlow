<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# Gate G1: Phase 1 Exit Criteria & Evidence

**Phase:** Phase 1 Foundation, Access & Web Shell (Master M1.6, Gate G1)  
**Evaluated:** 2026-10-04  
**Status:** **CONDITIONAL** (corrected 2026-10-19): criteria 2–6 pass with the evidence cited; criteria 1 and 7 are partial, and M1.6-T7 and T9 have open items (§3). Open follow-ups: #380, #381, #382, #386, #388, #389.  

---

## 1. Executive Summary

Gate G1 defines the technical and operational completion gate for Phase 1 of AssetFlow. It ensures that the core multi-tenant security architecture, cryptographic foundations, authentication and session flows, authorization matrix, notifications pipeline, and deployment automation operate with verifiable integrity before Phase 2 industrial domain modules are installed.

---

## 2. Gate G1 Criteria & Verification Evidence

| # | Gate G1 Criterion | Status | Evidence Reference | Technical Verification Details |
|---|---|:---:|---|---|
| **1** | **Full Profile Sign-in & Providers**<br>Sign-in through Zitadel, member provisioning by policy, and all providers healthy. | **PARTIAL** | `scripts/bootstrap.sh --profile full`<br>`backend/tests/e2e_api/test_session_flow.py`<br>`scripts/smoke-full.py` | Zitadel OIDC authentication flow, AES-256-GCM encrypted session cookies, and automated member provisioning policies (`invite_only`, `require_role`, `open`). All four production provider pillars (auth: `oidc`, secrets: `openbao`, telemetry: `otel`, events: `postgres`) report healthy. *Open:* the full profile has no `web` service, so browser sign-in cannot run in it yet (#388). |
| **2** | **Minimal Profile Standalone**<br>The minimal profile operates without external cloud services or network access. | **PASSED** | `deploy/compose.minimal.yml`<br>`scripts/bootstrap.sh --profile minimal` | Operates completely self-contained with PostgreSQL RLS, built-in mock auth, file secrets, in-memory events, and local Mailpit SMTP trap. (Start-up time has not been measured.) |
| **3** | **Tenant Isolation & Scope Leakage**<br>Zero cross-tenant data leakage; isolation and worker separation tests pass. | **PASSED** | `make test-isolation`<br>`backend/tests/isolation/` | PostgreSQL Row-Level Security (RLS) forced across all tenant tables. Every query filtered by `tenant_transaction` session context (`app.current_organization_id`). Worker processes operate with least-privilege credentials. |
| **4** | **Authorization Matrix Verification**<br>Every route × role permutation verified against permissions and negative denials. | **PASSED** | `backend/tests/authz_matrix/test_matrix.py`<br>`docs/guides/testing.md` | 100% of API endpoints declare machine-readable `x-assetflow-permission` or `x-assetflow-public`. Automated test asserts 2xx on allowed roles and 403/404 on denied roles. Bidirectional platform-tenant boundary verified. |
| **5** | **RLS Enforcement Gate in CI**<br>A table without row-level security is blocked in CI. | **PASSED** | `scripts/check-migrations.py`<br>`make lint-backend` | AST migration checker scans all Alembic revision files. Fails with non-zero exit code if any newly created tenant table lacks `ENABLE ROW LEVEL SECURITY`, `FORCE ROW LEVEL SECURITY`, or the 4 required tenant isolation policies. |
| **6** | **End-to-End Notifications Pipeline**<br>Multi-channel delivery, retries, dead-letter queue, and failure handling. | **PASSED** | `backend/tests/e2e_api/test_inbox_api.py`<br>`backend/tests/integration/test_notification_sender.py`<br>`backend/tests/e2e_api/test_notifications_acceptance.py` | In-app notifications with unread counter, email delivery via SMTP/Mailpit, webhook delivery with HMAC-SHA256 signatures, exponential backoff retries, and dead-letter queue alert generation. |
| **7** | **OWASP ASVS 5.0 Level 2 Checklist**<br>Checklist file exists with every requirement mapped to controls and tests. | **PARTIAL** | `docs/security/asvs-l2.md`<br>`scripts/gen-asvs-checklist.py --check` | A self-assessment of 51 selected Level 1 and 2 requirements (reworded, ASVS 4.0 chapter names), not the full ASVS 5.0 list (#389). Every `met`/`partial` row cites code and tests that exist (`--check` enforces it): 44 met, 6 partial, 1 open. |

---

## 3. Milestone M1.6 Verification Log

- **M1.6-T1 (Shell Foundation & Themes):** Dark, light, and high-contrast themes verified. Navigation shell, responsive sidebar, breadcrumbs, and WCAG AA contrast ratios validated.
- **M1.6-T2 (BFF Session & Authentication):** Session endpoints (`/api/auth/session`, `/api/auth/refresh`, `/api/auth/logout`), idle timeout modal with 60-second warning countdown, and 403 Forbidden screens verified.
- **M1.6-T3 (Internationalization & Locale):** `i18next` with RTL awareness, date-fns localized date/currency formatting, zero un-interpolated raw strings.
- **M1.6-T4 (Administration & Core Screens):** Dashboard, Org Units tree, Locations, Teams, Members, Member Profile, Effective Access Matrix, Installed Modules, and Organization Settings verified responsive from 320px to 2560px.
- **M1.6-T5 (Notification Center):** Header bell icon, real-time unread badge, flyout inbox, delivery log viewer, and member preferences matrix verified against M1.5 backend endpoints.
- **M1.6-T6 (Schema-Driven Admin Forms):** Dynamic Pydantic JSON Schema forms with field-level validation, tooltips, and client-side error reflection.
- **M1.6-T7 (Hardening & Security Headers):** Strict CSP (`default-src 'self'`), HSTS, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`. Minimal-profile containers run non-root with read-only root filesystems and `cap_drop: [ALL]`; the `api` and `web` services got this in part 10 (#356), checked by `scripts/tests/test_compose_minimal.py`. *Open (corrected 2026-10-19):* the full profile is not hardened yet (#388), and no container has a memory limit yet, so `scripts/check-container-hardening.py` does not pass (#386).
- **M1.6-T8 (One-Command Bootstrap):** `scripts/bootstrap.sh` and `setup.bat` verified on clean environments for both `minimal` and `full` profiles.
- **M1.6-T9 (Backup, Recovery & DR Runbooks):** pgBackRest AES-256 encrypted backups, S3 Object Lock compliance storage, field-level encryption canary verification, `make restore`, and automated monthly restore drill (`scripts/restore-test.sh`). *Open (corrected 2026-10-19):* WAL archiving is not configured (#382), nothing collects the backup metrics for the alerts (#381), and the restore drill does not yet restore a real backup (#380).

---

## 4. Conclusion & Gate G1 Sign-off

Phase 1 development goals (Milestones M1.1 through M1.6) are implemented, with the open items listed above. Gate G1 is **CONDITIONAL** (corrected 2026-10-19; the original 2026-10-04 evaluation said PASSED): it becomes PASSED when criteria 1 and 7 and M1.6-T7/T9 are closed through #380, #381, #382, #386, #388 and #389.
