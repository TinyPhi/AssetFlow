<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# AssetManager to AssetFlow Port Map

**Specification:** Master Plan §B8, §B14.1, Gate G0.5 / Milestone M2.1–M2.4  
**Source Repository:** `individual-projects/assetmanager/`  
**Target Repository:** `AssetFlow/`  
**Actions:**
- **Keep:** Code preserved as-is or with minor refactoring.
- **Adapt:** Code preserved in concept/structure but adapted to AssetFlow standards (UUIDv7, RLS, asyncpg, Zitadel OIDC, RFC 9457).
- **Port:** Feature logic migrated into modular domain structures (`modules/assets`, `modules/organization`, etc.).
- **Replace:** Legacy or proprietary implementation replaced by modern architectural standard (e.g. Zitadel for authNexus, outbox for synchronous hooks).
- **Rewrite:** Redesigned on new engine (e.g. WeasyPrint HTML templates for ReportLab).
- **Drop:** Deprecated, redundant, or obsolete implementation removed.
- **Defer:** Action deferred to platform monitoring tools (e.g. log viewing to Grafana/OTel).
- **Never-copy:** Proprietary, production data, or developer-specific artifacts strictly forbidden from open source repo.

---

## 1. Backend Server Mapping (`Server/`)

### 1.1 Core Layer (`Server/core/`)

| AssetManager File | Action | AssetFlow Target | Milestone | Rationale & Architectural Notes |
| :--- | :---: | :--- | :---: | :--- |
| `core/analytics_timeseries.py` | **Port** | `backend/app/modules/assets/analytics/timeseries.py` | M2.3 | Scope-aware timeseries aggregation queries for asset metrics. |
| `core/api_response.py` | **Adapt** | `backend/app/core/envelope.py` & `backend/app/core/problems.py` | M1.3 | Envelope for success (2xx) plus RFC 9457 Problem Details for errors. |
| `core/asset_db_types.py` | **Port** | `backend/app/modules/assets/models.py` | M2.1 | Custom field types and database type mapping. |
| `core/asset_status.py` | **Port** | `backend/app/modules/assets/lifecycle.py` | M2.1 | Domain template lifecycle transitions and validation. |
| `core/auth.py` | **Drop** | — | — | Obsolete duplicate authentication helper. |
| `core/auth_middleware.py` | **Adapt** | `backend/app/core/auth_middleware.py` | M1.3 | Enforces JWT token verification, BFF session cookies, and `Principal` injection. |
| `core/authnexus.py` | **Replace** | `backend/app/providers/auth/oidc.py` | M1.3 | Replaced proprietary authNexus gateway client with RFC-compliant OIDC provider (Zitadel preset). |
| `core/authz.py` | **Replace** | `backend/app/core/permissions.py` | M1.3 | Replaced static roles with hierarchical RBAC, permission strings, and `ScopeFilter`. |
| `core/client_ip.py` | **Keep** | `backend/app/core/client_ip.py` | M1.3 | Secure client IP extraction behind trusted reverse proxies. |
| `core/employee_dashboard.py` | **Port** | `backend/app/modules/assets/analytics/dashboard.py` | M2.3 | Modular dashboard aggregators supporting personal, team, and organization views. |
| `core/errors.py` | **Adapt** | `backend/app/core/problems.py` | M1.3 | Consolidated into RFC 9457 error problem hierarchy. |
| `core/middleware.py` | **Keep** | `backend/app/core/middleware.py` | M1.3 | CORS and Request ID middleware using UUIDv7 headers. |
| `core/observability.py` | **Keep** | `backend/app/providers/telemetry/otel.py` | M1.3 | OpenTelemetry tracer/meter with automated PII & credential scrubbing. |
| `core/pdf_footer.py` | **Rewrite** | `backend/app/modules/audit/pdf/` | M2.3 | Replaced ReportLab canvas hooks with HTML/CSS headers/footers in WeasyPrint (D16). |
| `core/postgres.py` | **Adapt** | `backend/app/core/db.py` | M1.3 | Replaced raw connection pool with asyncpg, `tenant_transaction()`, and RLS session variable enforcement. |
| `core/settings.py` | **Adapt** | `backend/app/core/config.py` | M1.3 | Replaced `.env` loader with Pydantic v2 YAML loader, environment overrides, and `secret://` references. |
| `core/ttl_cache.py` | **Keep** | `backend/app/core/cache.py` | M1.3 | In-memory asynchronous TTL cache for discovery and JWKS keys. |

---

### 1.2 Routers Layer (`Server/routers/`)

| AssetManager File | Action | AssetFlow Target | Milestone | Rationale & Architectural Notes |
| :--- | :---: | :--- | :---: | :--- |
| `routers/api_auth.py` | **Adapt** | `backend/app/modules/organization/auth_router.py` | M1.4 | BFF login, callback, token refresh, and logout routes. |
| `routers/api_v1_assets.py` | **Port** | `backend/app/modules/assets/router.py` | M2.1 | Split into sub-routers (catalog, lifecycle, components); enforce `organization_id` & `version`. |
| `routers/api_v1_assignments.py` | **Port** | `backend/app/modules/assets/custody/router.py` | M2.2 | Custody assignments, returns, acknowledgements; dispatches outbox events. |
| `routers/api_v1_authz.py` | **Replace** | `backend/app/modules/organization/authz_router.py` | M1.4 | RBAC role grants and effective permission inspection endpoints. |
| `routers/api_v1_employees.py` | **Port** | `backend/app/modules/organization/members/router.py` | M1.4 | Renamed "employees" to "members" (§C1.2); split directory and profile endpoints. |
| `routers/api_v1_meta.py` | **Port** | `backend/app/modules/assets/meta_router.py` | M2.1 | Asset categories, locations, suppliers, and custom fields metadata CRUD. |
| `routers/api_v1_notifications.py` | **Adapt** | `backend/app/modules/notifications/router.py` | M1.5 | In-app notification inbox, read/unread states, and preference toggles. |
| `routers/api_v1_qr.py` | **Port** | `backend/app/modules/assets/qr/router.py` | M2.2 | QR batch reservation, token hashing, and public scan resolution. |
| `routers/api_v1_settings.py` | **Port** | `backend/app/modules/organization/settings/router.py` | M1.4 | Multi-tenant organization settings persistence. |
| `routers/health.py` | **Replace** | `backend/app/main.py` | M1.3 | Replaced by standard `/healthz` and `/api/health` provider probes. |
| `routers/observability.py` | **Defer** | — | — | Deferred direct log viewer; operators use Grafana dashboards (§B14.1). |

---

### 1.3 Services Layer (`Server/services/`)

| AssetManager File | Action | AssetFlow Target | Milestone | Rationale & Architectural Notes |
| :--- | :---: | :--- | :---: | :--- |
| `services/acknowledgement_sweep_service.py` | **Port** | `backend/app/workers/sla_sweeper.py` | M1.5 | Migrated from in-process thread to standalone background worker job. |
| `services/asset_csv_export_service.py` | **Port** | `backend/app/modules/assets/export/service.py` | M2.3 | Formula-safe CSV/XLSX export execution inside worker with quota limits. |
| `services/asset_history_pdf_service.py` | **Rewrite** | `backend/app/modules/audit/pdf/asset_history.py` | M2.3 | HTML/WeasyPrint rendering replacing ReportLab. |
| `services/asset_service.py` | **Port** | `backend/app/modules/assets/service.py` | M2.1 | Core asset business logic, validation, and optimistic concurrency version checking. |
| `services/assignment_service.py` | **Port** | `backend/app/modules/assets/custody/service.py` | M2.2 | Custody state machine, transfer logic, reminder sweeps, and outbox event publishing. |
| `services/audit_service.py` | **Adapt** | `backend/app/modules/audit/service.py` | M1.4 | Writes to single partitioned `audit_events` store with personal value isolation. |
| `services/audit_trail_pdf_service.py` | **Rewrite** | `backend/app/modules/audit/pdf/audit_trail.py` | M2.3 | HTML/WeasyPrint audit trail PDF generation. |
| `services/authnexus_m2m.py` | **Replace** | `backend/app/providers/auth/oidc.py` | M1.3 | Standard client credentials grant (Zitadel machine users). |
| `services/authnexus_service.py` | **Replace** | `backend/app/modules/organization/provisioning.py` | M1.4 | Replaced proprietary roster sync with generic JIT/SCIM provisioning policy (§B5.6). |
| `services/avatar_service.py` | **Port** | `backend/app/modules/organization/members/avatar_service.py` | M2.3 | Avatar upload validation (magic bytes, dimensions) and database storage. |
| `services/employee_directory_service.py` | **Port** | `backend/app/modules/organization/members/directory_service.py` | M1.4 | Member directory search with scope-filtering and org unit hierarchy. |
| `services/holder_hydration_service.py` | **Port** | `backend/app/modules/assets/custody/holder_hydration.py` | M2.2 | Polymorphic holder resolution (member, team, or location). |
| `services/hooks.py` | **Replace** | `backend/app/providers/events/` | M1.3 | Replaced synchronous in-memory hooks with transactional outbox events. |
| `services/notifications/adapter.py` | **Replace** | `backend/app/channels/email.py` | M1.5 | Replaced external microservice call with native asynchronous SMTP channel connector. |
| `services/notifications/orchestrator.py` | **Adapt** | `backend/app/modules/notifications/service.py` | M1.5 | In-app inbox delivery and channel dispatch coordination. |
| `services/qr_label_pdf_service.py` | **Rewrite** | `backend/app/modules/assets/qr/label_pdf.py` | M2.2 | Configurable printable QR sticker sheets rendered via HTML/CSS. |
| `services/qr_service.py` | **Port** | `backend/app/modules/assets/qr/service.py` | M2.2 | Pre-generated QR batch pools, reservation, and tag assignment. |
| `services/roster_service.py` | **Replace** | `backend/app/modules/organization/provisioning.py` | M1.4 | Replaced by Zitadel identity claims mapping and `require_role` provisioning. |
| `services/scan_telemetry.py` | **Port** | `backend/app/modules/assets/qr/telemetry.py` | M2.2 | Scan rate tracking, geo/user-agent auditing, and anomaly detection. |
| `services/scan_token_service.py` | **Port** | `backend/app/modules/assets/qr/token_service.py` | M2.2 | 128-bit capability token generation, SHA-256 storage, and rotation. |

---

### 1.4 Repositories Layer (`Server/repositories/`)

| AssetManager File | Action | AssetFlow Target | Milestone | Rationale & Architectural Notes |
| :--- | :---: | :--- | :---: | :--- |
| `repositories/app_settings_repository.py` | **Port** | `backend/app/modules/organization/settings/repository.py` | M1.4 | Tenant-scoped key-value settings repository. |
| `repositories/asset_detail_repository.py` | **Port** | `backend/app/modules/assets/detail_repository.py` | M2.1 | Joined asset read queries with custody history and components. |
| `repositories/asset_repository.py` | **Port** | `backend/app/modules/assets/repository.py` | M2.1 | Core asset read repository with `ScopeFilter`. |
| `repositories/asset_write_repository.py` | **Port** | `backend/app/modules/assets/write_repository.py` | M2.1 | Insert/update operations with strict `version` concurrency checks. |
| `repositories/assignment_repository.py` | **Port** | `backend/app/modules/assets/custody/repository.py` | M2.2 | Custody records read operations with `ScopeFilter`. |
| `repositories/assignment_write_repository.py` | **Port** | `backend/app/modules/assets/custody/write_repository.py` | M2.2 | Custody state machine writes with transaction safety. |
| `repositories/audit_repository.py` | **Adapt** | `backend/app/modules/audit/repository.py` | M1.4 | Append-only partitioned audit log repository. |
| `repositories/avatar_repository.py` | **Port** | `backend/app/modules/organization/members/avatar_repository.py` | M2.3 | Binary image persistence for member profiles. |
| `repositories/db.py` | **Adapt** | `backend/app/core/db.py` | M1.3 | Consolidated into core asyncpg pool manager. |
| `repositories/employee_repository.py` | **Port** | `backend/app/modules/organization/members/repository.py` | M1.4 | Member profile and org unit assignment repository. |
| `repositories/errors.py` | **Adapt** | `backend/app/core/problems.py` | M1.3 | Data layer exception mappings to RFC 9457 problems. |
| `repositories/meta_repository.py` | **Port** | `backend/app/modules/assets/meta_repository.py` | M2.1 | Asset categories, locations, suppliers, and custom fields metadata repository. |
| `repositories/notification_repository.py` | **Port** | `backend/app/modules/notifications/repository.py` | M1.5 | Notification inbox entries and read state tracking. |
| `repositories/qr_repository.py` | **Port** | `backend/app/modules/assets/qr/repository.py` | M2.2 | QR batch and reservation pools repository. |
| `repositories/scan_event_repository.py` | **Port** | `backend/app/modules/assets/qr/scan_event_repository.py` | M2.2 | Partitioned scan audit events log repository. |

---

### 1.5 Schemas Layer (`Server/schemas/`)

| AssetManager File | Action | AssetFlow Target | Milestone | Rationale & Architectural Notes |
| :--- | :---: | :--- | :---: | :--- |
| `schemas/asset.py` | **Port** | `backend/app/modules/assets/schemas.py` | M2.1 | Pydantic v2 request/response schemas with custom fields validation. |
| `schemas/assignment.py` | **Port** | `backend/app/modules/assets/custody/schemas.py` | M2.2 | Assignment, return, and acknowledgement payload models. |
| `schemas/envelope.py` | **Keep** | `backend/app/core/envelope.py` | M1.3 | Pydantic v2 `ApiEnvelope` and `ResponseMeta`. |
| `schemas/qr.py` | **Port** | `backend/app/modules/assets/qr/schemas.py` | M2.2 | Batch generation, capability token, and scan response schemas. |

---

### 1.6 Other Server Files (`Server/`)

| AssetManager File | Action | AssetFlow Target | Milestone | Rationale & Architectural Notes |
| :--- | :---: | :--- | :---: | :--- |
| `Server/main.py` | **Adapt** | `backend/app/main.py` | M1.3 | FastAPI app factory, lifespan, CORS, middleware, routers. |
| `Server/app.py` | **Drop** | — | — | Redundant entry point wrapper. |
| `Server/read_docx.py` | **Drop** | — | — | One-off document parsing scratch script. |
| `Server/script.py` | **Drop** | — | — | Ad-hoc debug script. |
| `Server/scripts/import_v2_from_sheet.py` | **Rewrite** | `scripts/demo-data.py` | M2.4 | Transformed into neutral sample organization data seeder. |
| `Server/scripts/pg_seed_dummy.py` | **Rewrite** | `scripts/demo-data.py` | M2.4 | Replaced by multi-tenant sample data generator. |
| `Server/scripts/smoke_api_v1_assignments.py` | **Adapt** | `backend/tests/e2e_api/test_assignments.py` | M2.2 | Migrated into pytest API E2E test suite. |
| `Server/Dockerfile` | **Adapt** | `backend/Dockerfile` | M1.6 | Multi-stage non-root container image with uv. |
| `Server/requirements.txt` | **Adapt** | `backend/pyproject.toml` | M1.2 | Migrated to modern pyproject with pinned dependency bounds. |
| `Server/launch-otel-server.ps1` | **Drop** | — | — | Replaced by compose.full.yml otel service. |
| `Server/SERVER_README.md` | **Adapt** | `docs/` | M1.1 | Documentation distributed into Diátaxis structure. |
| `Server/vercel.json` | **Drop** | — | — | Vercel deployment replaced by standard Docker/Nginx stack. |
| `Server/tests/e2e/**` (Playwright) | **Adapt** | `backend/tests/e2e_api/` | M2.4 | Scenarios mapped to API E2E tests and manual release checklist. |

---

## 2. Frontend Client Mapping (`Client/src/`)

### 2.1 Infrastructure, Hooks & Shell

| AssetManager Path | Action | AssetFlow Target | Milestone | Rationale & Architectural Notes |
| :--- | :---: | :--- | :---: | :--- |
| `src/App.tsx` | **Adapt** | `frontend/src/App.tsx` | M1.6 | Application root routing, theme provider, and query provider. |
| `src/main.tsx` | **Adapt** | `frontend/src/main.tsx` | M1.6 | Vite entry point mounting React root. |
| `src/index.css` | **Adapt** | `frontend/src/index.css` | M1.6 | CSS reset and root typography styles. |
| `src/styles/tokens.css` | **Port** | `frontend/src/styles/tokens.css` | M1.6 | Semantic color system (light/dark theme tokens). |
| `src/styles/global.css` | **Port** | `frontend/src/styles/global.css` | M1.6 | Utility classes and typography hierarchy. |
| `src/styles/themeAndResponsive.test.ts` | **Port** | `frontend/src/styles/theme.test.ts` | M1.6 | Regression test for theme variables and responsive breakpoints. |
| `src/hooks/useOnlineStatus.ts` | **Port** | `frontend/src/app/useOnlineStatus.ts` | M1.6 | Window online/offline listener hook. |
| `src/hooks/useIdleTimeout.ts` | **Port** | `frontend/src/features/auth/hooks/useIdleTimeout.ts` | M1.6 | Inactivity detection and automated session expiration. |
| `src/hooks/useToast.tsx` | **Port** | `frontend/src/app/ToastProvider.tsx` | M1.6 | Toast notification hook and provider context. |
| `src/hooks/` (9 other hooks: `useBreadcrumbOverride`, `useCustodyNotifications`, `useDocumentTitle`, `useHoverOpen`, `useInfiniteScrollSentinel`, `useModalScrollLock`, `useNotificationReads`, `usePendingAcknowledgements`, `useRefreshableLoader`) | **Port** | `frontend/src/hooks/` | M1.6 | Utility UI hooks ported to strict TypeScript. |
| `src/components/common/ToastProvider.tsx` | **Port** | `frontend/src/app/ToastProvider.tsx` | M1.6 | Semantic token toast system with accessibility roles. |
| `src/api.ts` (legacy) | **Drop** | — | — | Dropped legacy untyped axios wrapper. |
| `src/utils/authNexus.api.ts` | **Replace** | `frontend/src/lib/auth/oidc.ts` | M1.6 | Replaced with standard OIDC authorization code + PKCE flow. |
| `src/utils/authService.ts` | **Adapt** | `frontend/src/lib/auth/session.ts` | M1.6 | BFF session management via secure HttpOnly cookies. |
| `src/otel-telemetry.ts` | **Keep** | `frontend/src/lib/telemetry.ts` | M1.6 | Client-side OpenTelemetry Web SDK initialization. |
| `src/queryClient.ts` | **Keep** | `frontend/src/queryClient.ts` | M1.6 | TanStack Query client configuration. |
| `src/vite-env.d.ts` | **Keep** | `frontend/src/vite-env.d.ts` | M1.2 | Vite client environment types. |
| `src/types/api.ts` | **Adapt** | `frontend/src/types/api.ts` | M1.6 | Typed API response models. |

---

### 2.2 Feature Components & Views (Directory Summaries & Counts)

Every non-test file in `Client/src` is cataloged below with directory-level counts:

| AssetManager Area | File Count | Action | AssetFlow Target | Milestone | Rationale & Architectural Notes |
| :--- | :---: | :---: | :--- | :---: | :--- |
| `src/components/common/` (including `illustrations/` [1] & `sidebar/` [7]) | 40 files | **Port** | `frontend/src/components/common/` | M1.6 | Breadcrumbs, confirm dialogs, pagination, filter popups, sidebar navigation, icons. |
| `src/components/ui/` (`AppIcon`, `AppLoader`, `Button`, `Skeleton`, `StatusPill`, `index`) | 6 files | **Port** | `frontend/src/components/ui/` | M1.6 | Reusable atomic UI components with semantic tokens. |
| `src/components/asset/` (History tables, timeline, change log, formatters) | 9 files | **Port** | `frontend/src/features/assets/custody/` | M2.2 | Custody history timelines, assignment cells, event details. |
| `src/components/assets/` (Tables, search filters, overlays, row actions, toolbars) | 14 files | **Port** | `frontend/src/features/assets/components/` | M2.1 | Catalog table with fuzzy filter, column selection, and export hooks. |
| `src/components/employees/` (Summary strip, search filters) | 3 files | **Port** | `frontend/src/features/organization/members/` | M1.4 | Member directory search filters and summary strip. |
| `src/components/form/` (Asset forms, member forms, batch modal, bulk update modals) | 20 files | **Port** | `frontend/src/features/assets/forms/` & `organization/members/` | M2.1 / M1.4 | Multi-section forms with dynamic custom fields and category templates. |
| `src/components/home/` (Overview KPIs, story cards, quick facts) | 9 files | **Port** | `frontend/src/features/dashboard/` | M2.3 | Dashboard overview cards, KPI boxes, and status summaries. |
| `src/components/logs/` (Audit table, actors, date filters, export dialogs) | 15 files | **Port** | `frontend/src/features/audit/` | M1.4 | Audit log viewer, actor filter, date range picker, and export dialog. |
| `src/components/notifications/` (Acknowledgement list, custody activity, warranty banners) | 11 files | **Port** | `frontend/src/features/notifications/` | M1.5 | Notification bell drawer, acknowledgement action cards, warranty alerts. |
| `src/components/pages/` (Root pages: AllAssets, AssetDetail, AuthCallback, Employee, EmployeeDetail, Home, LogViewer, LogsPage, NewAsset, Notifications, QrBatches, ScanPage, Settings) | 13 files | **Port** | `frontend/src/pages/` | M1.4–M2.3 | Primary screen views for assets, members, notifications, settings, and scanning. |
| `src/components/pages/analytics/` (Charts, calendar heatmap, acquisition lines, presets) | 21 files | **Port** | `frontend/src/features/assets/analytics/` | M2.3 | Timeseries charts, calendar heatmaps, distribution bars. |
| `src/components/pages/dashboard/` (including `sections/` [6] & `ui/` [4]) | 33 files | **Port** | `frontend/src/features/assets/dashboard/` | M2.3 | Diorama visualizer, activity timelines, executive KPI cards. |
| `src/components/pages/newAsset/` (`BulkImportHint.tsx`) | 1 file | **Port** | `frontend/src/features/assets/forms/` | M2.1 | Template guidelines and bulk import helper card. |
| `src/components/qr/` (Cards, download button, status badge, batches table) | 5 files | **Port** | `frontend/src/features/assets/qr/` | M2.2 | Printable QR sheet previews and batch lifecycle management. |
| `src/components/settings/` (Profile card, security, appearance, preferences, password) | 17 files | **Port** | `frontend/src/features/settings/` | M1.6 | Member profile settings, appearance theme switcher, password change. |
| `src/components/app/` (TopBar, NotificationBell, AccountMenu, route guards, auth bootstrap) | 9 files | **Port** | `frontend/src/app/` | M1.6 | App navigation header, auth state bootstrap, and route guards. |
| `src/queries/` (`assets`, `authz`, `avatar`, `dashboard`, `employees`, `meta`, `qr`) | 7 files | **Port** | `frontend/src/queries/` | M1.4–M2.3 | TanStack Query factory hooks and cache invalidators. |
| `src/services/` (`acknowledgement`, `asset`, `assignment`, `authz`, `avatar`, `employee`, `meta`, `password`, `qr`) | 9 files | **Port** | `frontend/src/services/` | M1.4–M2.3 | API service abstraction layer for frontend queries. |
| `src/utils/` (Bulk import, XLSX export, formatters, avatar, pagination, time, theme) | 21 files | **Port** | `frontend/src/utils/` | M1.4–M2.3 | Formula-safe exports, CSV parsers, relative time formatters, theme helpers. |
| `src/constants/` (`acknowledgement`, `auditLog`, `errorPages`, `loading`, `notificationRecipients`, `passwordReset`) | 7 files | **Port** | `frontend/src/constants/` | M1.6 | UI constants, navigation definitions, and status codes. |
| `src/data/` (`address.json`, `assetInfoHint.json`, `employeeInfoHint.json`, `notifications.InfoHint.json`) | 4 files | **Port** | `frontend/src/data/` | M1.6 | Static hints, address catalogs, and UI metadata. |
| `src/api/` (`apiClient.ts`, `logsApi.ts`) | 2 files | **Port** | `frontend/src/api/` | M1.6 | Core fetch client and log query helpers. |

---

## 3. Disallowed, Proprietary & Dropped Artifacts

| Source Pattern / File | Action | Reason (§B14.1, Decision 4, Decision 38) |
| :--- | :---: | :--- |
| `**/.env*`, `pgpassfile/` | **Never-copy** | Environment and password files containing credentials and secret URLs. |
| `logs/`, `DB/backups/`, `prod_*.sql` | **Never-copy** | Production database dumps and operational logs containing real company data. |
| `**/.coverage`, `**/test-results/` | **Never-copy** | Local build and test execution artifacts. |
| `**/.pytest_cache/`, `**/.ruff_cache/`, `**/.mypy_cache/` | **Never-copy** | Local tool and compiler caches. |
| `Notes/**` | **Never-copy** | Internal engineering notes, meeting transcripts, and proprietary communications. |
| `old CLAUDE.md`, `.claude/**` | **Never-copy** | Legacy proprietary prompt configurations and vendor hooks. |
| `recycle_bin_entries`, `v_recycle_bin` | **Drop** | Hard-deletion/recovery table; AssetFlow uses explicit status lifecycle. |
| `DB/init.sql` | **Drop** | Replaced by versioned Alembic migrations with RLS. |
| `Server/scripts/pg_seed_dummy.py` | **Rewrite** | Replaced by neutral multi-tenant `scripts/demo-data.py` (M2.4). |
| `Server/scripts/import_v2_from_sheet.py` | **Rewrite** | Replaced by neutral multi-tenant `scripts/demo-data.py` (M2.4). |
| `individual-projects/TMMS-WEB/**` (code) | **Never-copy** | Replaced by cleanroom implementation in Phase 3 (§B14.2). |
