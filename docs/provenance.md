<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# Component Provenance and Porting Record

This document records the exact provenance, licensing origin, source commit snapshots, and porting status for all components transitioned into AssetFlow per master plan §B2, §B14, and M1.1-T12.

---

## 1. Source Snapshot Commit Baselines

Source repositories audited during Phase 0 preparation (Gate G0 baseline):

| Source Project | Git Commit SHA | Branch | License Context |
| --- | --- | --- | --- |
| **AssetManager** | `babc8ccba170c9b42ee72e21f2e8beb4ab0fbc66` | `main` | TinyPhi proprietary baseline; clean-room porting into AGPL-3.0-only |
| **TMMS-WEB** | `d422c1067a760a8e0df5ac843b4c9efe5a14c859` | `main` | TinyPhi maintenance concept; vision adopted, legacy models dropped |

---

## 2. Provenance and Clean-Room Guardrails

1. **Clean-room rule**: No raw code with proprietary names, unrotated secrets, or single-tenant assumptions is copied directly into `AssetFlow`.
2. **Never-copy paths**: `.env*`, `Notes/`, `.claude/`, `CLAUDE.md`, and production database dumps (`prod_*.sql`) are strictly prohibited from entry into this repository.
3. **OpenWind policy (§B2.3)**: AssetFlow adopts architectural patterns and engineering standards from OpenWind, not code. Any OpenWind code translation requires written authorization and explicit attribution.

---

## 3. Component Porting Matrix (§B14)

### 3.1 AssetManager → AssetFlow (§B14.1)

| # | AssetManager Source Component | AssetFlow Destination | Origin / Type | Source Commit | Action & Technical Notes | Porter | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `core/api_response.py`, `schemas/envelope.py` | `core/envelope.py`, `core/problems.py` | AssetManager | `babc8cc` | Keep envelope for success responses; change error responses to RFC 9457 Problem Details | TinyPhi Engineering | `planned` |
| 2 | `core/postgres.py`, `repositories/db.py` | `core/db.py` | AssetManager | `babc8cc` | Adapt: organization context per transaction (`SET LOCAL`), transaction helper, statement timeout, PgBouncer support | TinyPhi Engineering | `planned` |
| 3 | `core/settings.py` | `core/config.py` | AssetManager | `babc8cc` | Adapt: YAML + environment + `secret://` references; keep buffered startup warnings | TinyPhi Engineering | `planned` |
| 4 | `core/observability.py`, `core/middleware.py`, `core/client_ip.py` | `providers/telemetry/otel.py`, `core/middleware.py` | AssetManager | `babc8cc` | Keep and generalize: OTLP exporter, config-driven telemetry scrubber | TinyPhi Engineering | `planned` |
| 5 | `core/authnexus.py`, `core/auth_middleware.py`, `routers/api_auth.py` | `providers/auth/oidc.py`, `core/auth_middleware.py`, `modules/organization/auth_router.py` | AssetManager | `babc8cc` | Adapt: standard OIDC discovery with Zitadel preset; keep BFF cookie hardening and add cookie encryption | TinyPhi Engineering | `planned` |
| 6 | `core/auth.py`, `auth/auth_nexus.py` | — | AssetManager | `babc8cc` | Drop (duplicate and obsolete auth code) | TinyPhi Engineering | `dropped` |
| 7 | `services/roster_service.py`, `services/authnexus_service.py`, `services/authnexus_m2m.py` | Provisioning policy (§B5.6) | AssetManager | `babc8cc` | Replace; "provisioned members only" rule kept as `require_role` | TinyPhi Engineering | `planned` |
| 8 | `core/authz.py` | `core/permissions.py` + scope resolver + `rbac` config | AssetManager | `babc8cc` | Replace with scoped RBAC permissions model (§B5.3) | TinyPhi Engineering | `planned` |
| 9 | `departments` table, department logic in employee services | `modules/organization` (org units tree, teams) | AssetManager | `babc8cc` | Replace and extend with hierarchical org units (`ltree`) and teams | TinyPhi Engineering | `planned` |
| 10 | `repositories/asset_*`, `services/asset_service.py`, `routers/api_v1_assets.py` | `modules/assets/` | AssetManager | `babc8cc` | Port and split into sub-routers; add `organization_id`, `version`, and scope filters | TinyPhi Engineering | `planned` |
| 11 | `v_asset_inventory` and other database views | `modules/assets/` read models | AssetManager | `babc8cc` | Port as `security_invoker` views covered by isolation suite | TinyPhi Engineering | `planned` |
| 12 | `services/assignment_service.py`, `repositories/assignment_*`, `routers/api_v1_assignments.py` | `modules/assets/custody/` | AssetManager | `babc8cc` | Port; deduplicate assign/return routes; custody notifications moved to outbox events | TinyPhi Engineering | `planned` |
| 13 | `services/qr_*`, `services/scan_token_service.py`, `services/scan_telemetry.py`, `repositories/qr_repository.py`, `repositories/scan_event_repository.py` | `modules/assets/qr/` | AssetManager | `babc8cc` | Port flagship QR feature; scan tokens stored cryptographically hashed | TinyPhi Engineering | `planned` |
| 14 | `services/*_pdf_service.py`, `core/pdf_footer.py` | `modules/audit/pdf/` (HTML + WeasyPrint) + worker runner | AssetManager | `babc8cc` | Rewrite using HTML templates and WeasyPrint (D16); large PDF exports offloaded to worker | TinyPhi Engineering | `planned` |
| 15 | `services/audit_service.py`, `repositories/audit_repository.py`, `admin_audit_log`, `role_audit_log`, `app_settings_audit` | `modules/audit/` | AssetManager | `babc8cc` | Consolidate into single partitioned `audit_events` store with erasable personal data table | TinyPhi Engineering | `planned` |
| 16 | `notifications` table, `services/notifications/adapter.py`, `orchestrator.py`, `routers/api_v1_notifications.py` | `modules/notifications/`, `channels/{inapp,email}.py` | AssetManager | `babc8cc` | Generalize: table becomes in-app inbox; email becomes direct SMTP channel; recipient rules via automation | TinyPhi Engineering | `planned` |
| 17 | `services/acknowledgement_sweep_service.py` | `workers/sla_sweeper.py` | AssetManager | `babc8cc` | Move sweep logic to asynchronous worker process | TinyPhi Engineering | `planned` |
| 18 | `repositories/employee_repository.py`, `routers/api_v1_employees.py`, `services/employee_directory_service.py`, `services/holder_hydration_service.py` | `modules/organization/members` | AssetManager | `babc8cc` | Port, rename to neutral terminology (`member`), split, drop proprietary identity migration code | TinyPhi Engineering | `planned` |
| 19 | `core/analytics_timeseries.py`, `core/employee_dashboard.py`, `routers/api_v1_meta.py` | `modules/assets/analytics/` | AssetManager | `babc8cc` | Port; adapt metrics to be scope-aware | TinyPhi Engineering | `planned` |
| 20 | `routers/api_v1_settings.py`, `repositories/app_settings_repository.py` | `modules/organization/settings` | AssetManager | `babc8cc` | Port as per-organization scoped settings | TinyPhi Engineering | `planned` |
| 21 | `services/avatar_service.py`, `repositories/avatar_repository.py` | `modules/organization/members` | AssetManager | `babc8cc` | Port avatar handling with magic-byte content validation | TinyPhi Engineering | `planned` |
| 22 | `core/ttl_cache.py` | `core/cache.py` | AssetManager | `babc8cc` | Keep in-memory single-flight TTL cache | TinyPhi Engineering | `planned` |
| 23 | `routers/observability.py` (log viewer proxy) | — | AssetManager | `babc8cc` | Defer (avoids coupling application to a specific log storage backend) | TinyPhi Engineering | `deferred` |
| 24 | `recycle_bin_entries`, `v_recycle_bin`, `is_deleted` columns | — | AssetManager | `babc8cc` | Drop (lifecycle status is the formal retirement mechanism) | TinyPhi Engineering | `dropped` |
| 25 | `DB/init.sql` | `backend/migrations/` | AssetManager | `babc8cc` | Rewrite as versioned raw SQL Alembic migrations with mandatory RLS | TinyPhi Engineering | `planned` |
| 26 | `scripts/import_v2_from_sheet.py`, `scripts/pg_seed_dummy.py`, dummy data | `scripts/demo-data.py` (`make demo-data`) | AssetManager | `babc8cc` | Rewrite as neutral multi-tenant sample organization for testing and demo | TinyPhi Engineering | `planned` |
| 27 | `Notes/`, `.claude/`, `CLAUDE.md`, production SQL dumps | — | AssetManager | `babc8cc` | Never copied (off-limits clean-room rule) | TinyPhi Engineering | `never-copy` |
| 28 | `Client/src/services/*`, `queries/*`, `components/ui/*`, `styles/tokens.css`, `hooks/*`, `ToastProvider` | `frontend/src/` | AssetManager | `babc8cc` | Port UI tokens, base components, toast notifications, and query hooks to React 19 SPA | TinyPhi Engineering | `planned` |
| 29 | `Client/src/api.ts` (legacy) | — | AssetManager | `babc8cc` | Not ported (superseded by modular API clients) | TinyPhi Engineering | `dropped` |
| 30 | `Client/src/utils/authNexus.api.ts`, `authService.ts` | `frontend/src/lib/{api,auth}` | AssetManager | `babc8cc` | Adapt to generic OIDC BFF with HttpOnly refresh cookies | TinyPhi Engineering | `planned` |
| 31 | Frontend Vitest suites | `frontend/src/**/*.test.ts` | AssetManager | `babc8cc` | Port component and hook unit tests | TinyPhi Engineering | `planned` |
| 32 | Frontend Playwright specs | API E2E tests + release checklist steps | AssetManager | `babc8cc` | Port functional assertions into backend API E2E flows and manual release checklist | TinyPhi Engineering | `planned` |

---

### 3.2 TMMS → AssetFlow (§B14.2)

| # | TMMS Source Component | AssetFlow Destination | Origin / Type | Source Commit | Action & Technical Notes | Porter | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 33 | Product vision: priority/severity workflows, smart scheduling, escalation, notifications | `docs/specs/maintenance-engine.md`, `modules/maintenance/` | TMMS Vision | `d422c10` | Becomes §B9 specifications; implemented as config-driven workflow and automation engines | TinyPhi Engineering | `planned` |
| 34 | `core/security.py` JWKS cache with TTL | `providers/auth/oidc.py` | TMMS | `d422c10` | Reuse verified in-memory TTL caching pattern for public OIDC keys | TinyPhi Engineering | `planned` |
| 35 | `services/user_service.py` get-or-create from claims | `modules/organization/` (provisioning) | TMMS | `d422c10` | Reuse claim hydration pattern governed by strict provisioning policy (§B5.6) | TinyPhi Engineering | `planned` |
| 36 | `utils/snowflake.py` | — | TMMS | `d422c10` | Dropped; superseded by UUIDv7 primary keys (D5) | TinyPhi Engineering | `dropped` |
| 37 | `utils/kafka_producer.py`, `workers/main.py` | `core/outbox.py`, `backend/workers/` | TMMS | `d422c10` | Replaced by transactional PostgreSQL outbox and dedicated worker (D9) | TinyPhi Engineering | `replaced` |
| 38 | `db/init.sql`, backend models | `modules/maintenance/` | TMMS | `d422c10` | Dropped; replaced by §B9 data model and versioned migrations | TinyPhi Engineering | `dropped` |
| 39 | Frontend, nginx config | `frontend/`, `deploy/nginx/` | TMMS | `d422c10` | Dropped; replaced by new React 19 SPA web shell and hardened nginx configuration | TinyPhi Engineering | `dropped` |
