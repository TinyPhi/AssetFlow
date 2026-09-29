# AssetManager Test Baseline & Coverage Report

**Date:** 2026-09-29  
**Source Code Inspected:** `individual-projects/assetmanager/` (read-only audit)  
**Task:** P0-02 (Gate G0.5 / Master Plan §B2.1 & Q18)

---

## 1. Executive Summary

| Test Suite | Location | Total Tests | Passed | Skipped | Failed | Coverage / Notes |
| --- | --- | --- | --- | --- | --- | --- |
| **Backend Unit Tests** | `Server/tests/` | 328 | 323 | 5 | 0 | **44%** line coverage across routers & services |
| **Live Auth / E2E Backend** | `tests/` | 51 | - | 51 (skipped) | 0 | Requires live PostgreSQL + authNexus |
| **Frontend Unit / Component** | `Client/src/**/*.test.ts(x)` | 164 | 164 | 0 | 0 | 18 test files, 100% pass rate in Vitest |
| **Frontend Playwright E2E** | `Client/e2e/*.spec.ts` | 17 | - | 17 (unrun) | 0 | 8 spec files (idle, login, qr, responsive, etc.) |

---

## 2. Backend Coverage Analysis (`Server/`)

Measured via `pytest tests --cov=services --cov=routers`:
- **Total Statements:** 3,409
- **Missed Statements:** 1,924
- **Overall Line Coverage:** **44%**

### Coverage by Service & Router

| Module | Statements | Missing | Coverage | Status / Gap Analysis |
| --- | --- | --- | --- | --- |
| `services/employee_directory_service.py` | 71 | 1 | **99%** | Fully tested roster caching and query filters |
| `services/holder_hydration_service.py` | 86 | 2 | **98%** | Fully tested holder name/email resolution |
| `services/authnexus_m2m.py` | 79 | 2 | **97%** | High coverage of M2M bearer validation |
| `services/roster_service.py` | 117 | 3 | **97%** | Single-flight, cache TTL, fallback logic covered |
| `services/asset_history_pdf_service.py` | 93 | 10 | **89%** | PDF generation and pagination covered |
| `services/qr_label_pdf_service.py` | 137 | 18 | **87%** | QR sheet layout and label formatting covered |
| `services/audit_service.py` | 41 | 8 | **80%** | Audit logging wrappers covered |
| `services/hooks.py` | 18 | 4 | **78%** | Pre/post event hooks covered |
| `routers/health.py` | 13 | 3 | **77%** | Basic health probes covered |
| `services/avatar_service.py` | 53 | 16 | **70%** | Magic byte sniffing and dimension resize covered |
| `services/qr_service.py` | 52 | 22 | **58%** | Batch pool generation covered |
| `routers/observability.py` | 153 | 68 | **56%** | OpenTelemetry spans and actor tracking |
| `routers/api_v1_authz.py` | 23 | 11 | **52%** | Minimal role authority endpoint checks |
| `services/audit_trail_pdf_service.py` | 246 | 121 | **51%** | Core PDF generation tested, edge formatting untested |
| `services/asset_service.py` | 63 | 34 | **46%** | Low coverage of direct asset mutations |
| `services/assignment_service.py` | 280 | 166 | **41%** | Core custody tested; complex edge transitions untested |
| `routers/api_v1_settings.py` | 92 | 56 | **39%** | Settings persistence mostly untested |
| `routers/api_v1_qr.py` | 81 | 52 | **36%** | Direct QR endpoints lightly tested |
| `routers/api_v1_notifications.py` | 61 | 39 | **36%** | Notification preferences and recipients |
| `services/acknowledgement_sweep_service.py` | 68 | 45 | **34%** | Sweep runner background loop untested |
| `services/notifications/adapter.py` | 51 | 34 | **33%** | Email delivery adapters lightly tested |
| `services/notifications/orchestrator.py` | 75 | 51 | **32%** | Notification recipient dispatch partially tested |
| `services/asset_csv_export_service.py` | 59 | 42 | **29%** | CSV export streaming untested |
| `routers/api_v1_assignments.py` | 76 | 54 | **29%** | Direct assignment REST endpoints untested |
| `routers/api_v1_meta.py` | 137 | 98 | **28%** | Metadata CRUD (categories, departments, locations) |
| `routers/api_auth.py` | 71 | 53 | **25%** | Only token validation tested; login endpoints untested |
| `routers/api_v1_employees.py` | 341 | 262 | **23%** | Heavy employee CRUD and profile endpoints untested |
| `routers/api_v1_assets.py` | 476 | 378 | **21%** | Core asset list/create/update REST endpoints untested |
| `services/authnexus_service.py` | 209 | 184 | **12%** | IdP discovery, token exchange, userinfo calls untested |
| `services/scan_telemetry.py` | 29 | 29 | **0%** | Untested in unit suite |
| `services/scan_token_service.py` | 58 | 58 | **0%** | Untested in unit suite |

---

## 3. Frontend Baseline (`Client/`)

### Vitest Unit / Component Tests (18 files, 164 passed)
- `src/constants/loading.test.ts` (5 tests)
- `src/utils/avatar.test.ts` (9 tests)
- `src/components/pages/dashboard/dashboardAggregates.test.ts` (13 tests)
- `src/components/pages/analytics/analyticsTransforms.test.ts` (19 tests)
- `src/components/pages/analytics/analyticsPresets.test.ts` (6 tests)
- `src/utils/inventoryBulkUpdate.test.ts` (4 tests)
- `src/components/assets/assetFilterParams.test.ts` (6 tests)
- `src/utils/devLog.test.ts` (11 tests)
- `src/components/pages/dashboard/dioramaData.test.ts` (10 tests)
- `src/components/pages/analytics/calendarTransforms.test.ts` (11 tests)
- `src/utils/assetBulkImport.test.ts` (10 tests)
- `src/components/logs/auditLog.test.ts` (23 tests)
- `src/components/asset/assetHistoryFormatters.test.ts` (8 tests)
- `src/components/asset/acknowledgementDisplay.test.ts` (8 tests)
- `src/styles/themeAndResponsive.test.ts` (4 tests)
- `src/components/common/FilterPopupSelect.test.tsx` (3 tests)
- `src/components/assets/AssetsSearchFilter.test.tsx` (7 tests)
- `src/components/employees/EmployeesSearchFilter.test.tsx` (7 tests)

### Playwright E2E Tests (8 spec files, 17 test cases)
- `e2e/assets.spec.ts`: List renders, search query synchronization, refresh port behavior, filter deselection (4 tests)
- `e2e/avatar.spec.ts`: Upload persistence across reload, size >50KB rejection (2 tests)
- `e2e/idle.spec.ts`: Inactivity warning and auto-logout (2 tests)
- `e2e/login.spec.ts`: Guest landing, public QR route reachability, full OIDC login flow (3 tests)
- `e2e/network.spec.ts`: Offline toast and reconnection behavior (2 tests)
- `e2e/notifications.spec.ts`: Unread dot, mark-all-read, scroll lock (2 tests)
- `e2e/qr-unused.spec.ts`: PDF download trigger (1 test)
- `e2e/responsive.spec.ts`: Viewport overflow checks (1 test)

---

## 4. Parity Checklist Seed: Untested AssetManager Features (for Milestone M2.4)

These features exist in AssetManager's source code but lack direct unit test coverage. They must have dedicated contract, unit, and isolation tests written during Phase 2 porting:

1. **Metadata & Org Configuration (`api_v1_meta.py`)**:
   - `GET / POST / PUT / DELETE /api/v1/meta/categories` (Category schema & custom field associations)
   - `GET / POST / PUT / DELETE /api/v1/meta/custom-fields` (Data type validations: text, number, date, boolean, select)
   - `GET / POST / PUT / DELETE /api/v1/meta/departments` (Department hierarchy & cascade rules)
   - `GET / POST / PUT / DELETE /api/v1/meta/locations` (Physical building / room management)
   - `GET / POST / PUT / DELETE /api/v1/meta/manufacturers` (Vendor directory)

2. **Core Asset Lifecycle Endpoints (`api_v1_assets.py`)**:
   - `POST /api/v1/assets` (Direct asset provisioning, category sequence assignment)
   - `PUT /api/v1/assets/{id}` (Field updates, optimistic concurrency checking)
   - `DELETE /api/v1/assets/{id}` (Soft deletion / disposal rules)
   - `asset_components` sub-assembly / peripheral tracking

3. **Background Services**:
   - `acknowledgement_sweep_service.py` (Periodic SLA sweep of unacknowledged asset assignments)
   - `scan_token_service.py` (HMAC token generation, TTL expiration, brute-force mitigation)
   - `scan_telemetry.py` (Geolocation redaction, IP anonymization on public scan)

4. **Frontend Untested Core Views**:
   - `Employee.tsx` (~1,240 lines): Employee master detail, assigned asset cards, department history
   - `AssetDetail.tsx`: Specification tabs, custody timeline, warranty countdown
   - Modal workflows: `AssetCreateModal.tsx`, `AssetEditModal.tsx`, `AssignmentModal.tsx`, `ReturnModal.tsx`
   - Administrative settings management views (`Settings.tsx`, `CustomFieldsManager.tsx`)
