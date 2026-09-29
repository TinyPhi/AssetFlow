# License, Provenance, and Sensitive File Scan Report

**Date:** 2026-09-29  
**Scope:** `individual-projects/assetmanager/` and `individual-projects/TMMS-WEB/`  
**Task:** P0-03 (Gate G0.8 / Master Plan §D1 G0.8, §B2, §B14.1, §C4.11, Q8, Q20)  
**Dual-Licensing Target:** AGPL-3.0-only + TinyPhi Commercial License

---

## 1. Executive Summary

This scan audits all third-party dependencies, bundled static assets, templates, proprietary code snippets, and operational artifacts across both legacy codebases to ensure clean-room compliance before any feature porting begins.

- **Dependency Licenses:** **Clean.** No viral GPL or static LGPL libraries detected. All backend and frontend dependencies use permissive or weak-copyleft licenses (MIT, Apache-2.0, BSD-2/3, ISC, SIL OFL-1.1) compatible with AGPL-3.0 and dual commercial distribution.
- **Static Assets & Branding:** **Replacement Required.** `jmv_logo.png`, proprietary icons, and company-specific templates are identified and slated for replacement with neutral SVG assets.
- **Sensitive Operational Files:** **Identified & Marked NEVER COPY.** Credentials, real database dumps (`prod_schema.sql`), `.env*` files, `pgpassfile`, and internal notes are isolated and permanently excluded from AssetFlow.
- **Secret Pattern Scan:** **12 findings in `assetmanager` (count only), 0 in `TMMS-WEB`** (beyond sample docker passwords). All secret values must be rotated and managed exclusively via OpenBao in production.

---

## 2. Dependency License Audit

### 2.1 Backend Dependencies (Python)

| Library / Package | License | Incompatible with AGPL / Commercial? | Decision / Action |
| --- | --- | :---: | --- |
| `fastapi`, `starlette`, `anyio` | MIT | No | **Keep** for AssetFlow backend core |
| `pydantic`, `pydantic-settings` | MIT | No | **Keep** for schema validation |
| `asyncpg` | Apache-2.0 | No | **Keep** for raw PostgreSQL async driver |
| `cryptography` | Apache-2.0 / BSD-3 | No | **Keep** for security/JWT primitives |
| `reportlab` (Open Source) | BSD-3-Clause | No | **Keep** for PDF generation; avoid ReportLab Plus |
| `pillow` | HPND (permissive) | No | **Keep** for image/avatar processing |
| `qrcode` | BSD-3-Clause | No | **Keep** for QR code generation |
| `openpyxl` | MIT | No | **Keep** for Excel import/export |
| `opentelemetry-*` | Apache-2.0 | No | **Keep** for telemetry provider interface |
| `pyiceberg`, `pyroaring` | Apache-2.0 / MIT | No | Evaluate necessity; keep if used in data pipelines |
| `strictyaml` | MIT | No | **Keep** for domain YAML validation |
| `kafka-python` (TMMS) | Apache-2.0 | No | **Drop** in 1.0 (PostgreSQL Outbox used instead per D7) |
| `alembic` (TMMS) | MIT | No | **Keep** for raw SQL migration runner |

### 2.2 Frontend Dependencies (Node.js)

| Library / Package | License | Incompatible with AGPL / Commercial? | Decision / Action |
| --- | --- | :---: | --- |
| `react`, `react-dom` | MIT | No | **Keep** (React 19) |
| `react-router-dom` | MIT | No | **Keep** for client SPA routing |
| `@tanstack/react-query` | MIT | No | **Keep** for server state caching |
| `@tanstack/react-virtual` | MIT | No | **Keep** for virtualized data tables |
| `axios` | MIT | No | **Keep** (or replace with native `fetch` client) |
| `lucide-react` | ISC | No | **Keep** for UI icons |
| `oidc-client-ts` | Apache-2.0 | No | **Keep** for Zitadel OIDC authentication |
| `three` | MIT | No | **Review** (3D visualization in AssetManager; evaluate necessity) |
| `@e965/xlsx` | Apache-2.0 | No | **Keep** for client-side sheet parsing |
| `@fontsource-variable/inter` | SIL OFL-1.1 | No | **Keep** (SIL OFL allows embedding and commercial bundling) |

---

## 3. Static Assets, Snippets, Fonts & Templates

| Asset / File | Origin / Source | License / Nature | Decision / Action |
| --- | --- | --- | --- |
| `Client/public/jmv_logo.png` | JMV / Company branding | Proprietary | **NEVER COPY**. Replace with neutral AssetFlow SVG mark. |
| `Client/public/apple-touch-icon.png` | JMV branding | Proprietary | **NEVER COPY**. Replace with neutral brand icon. |
| `Client/public/favicon.ico / .png` | JMV branding | Proprietary | **NEVER COPY**. Replace with generic AssetFlow favicon. |
| `Client/public/asset-import-template.xlsx` | AssetManager sample | Generic schema | **Replace** with clean neutral template in Phase 2. |
| `Client/public/inventory-update-template.xlsx`| AssetManager sample | Generic schema | **Replace** with clean neutral template in Phase 2. |
| `Client/public/error-page.webp` | Illustration | Unknown provenance | **Replace** with generated or verified open-license artwork. |
| Inter Font (`@fontsource-variable/inter`) | Rasmus Andersson | SIL OFL-1.1 | **Allowed**. Clean font provenance. |

---

## 4. Sensitive Operational Files (NEVER COPY)

The following paths in `individual-projects/` are classified as **strictly sensitive** and must **NEVER** be copied into the AssetFlow repository:

| Path / Pattern | Project | Classification | Risk / Reason |
| --- | --- | --- | --- |
| `pgpassfile/` | `assetmanager` | **Critical Secret** | Contains live PostgreSQL connection passwords. |
| `prod_schema.sql` | `assetmanager` | **Production Data Dump** | Contains real production schemas, sequence states, and table dumps. |
| `prod_users_sync.sql` | `assetmanager` | **PII & User Records** | Contains real user names, emails, and employee IDs. |
| `Notes/` | `assetmanager` | **Internal IP / Infrastructure** | Contains company infrastructure, authNexus notes, and internal architecture. |
| `logs/` | `assetmanager` | **Operational Logs** | May contain active tokens, actor IDs, and runtime stack traces. |
| `.env*` (root, Server, Client) | `assetmanager`, `TMMS-WEB` | **Credentials & Keys** | Contains live JWT secrets, client secrets, and database passwords. |
| `CLAUDE.md`, `.claude/` (old) | `assetmanager` | **Legacy Configuration** | Superseded by AssetFlow's gated `.claude` loop. |
| `test-results/` | Both | **Build Artifacts** | Ephemeral test results; excluded from git. |
| `perf/` | `assetmanager` | **Internal Benchmarks** | Raw performance run dumps; must not be copied. |

---

## 5. Secret Pattern Scan Summary

Automated pattern scan results over `individual-projects/`:

| Project | Category | Match Count | Detail / Files Involved | Action |
| --- | --- | :---: | --- | --- |
| **assetmanager** | Private Keys | 4 | Located in `.env*` files (`.env`, `.env.jmv.ams`, `.env.production`, `Server/.env`) | Do not copy `.env*`; rotate credentials; use OpenBao in production |
| **assetmanager** | Generic Passwords / Secrets | 6 | Located in internal documentation (`Notes/auth.implementation.md`, `email.service...md`) and mock test files | Internal docs never copied; test mocks sanitized |
| **assetmanager** | Database URI with Password | 2 | Located in test files (`test_settings_frontend_url.py`, `test_startup_warnings.py`) | Dummy values in tests; real DB creds never checked into git |
| **assetmanager** | **Total Findings** | **12** | *(Counts only; secret values suppressed)* | Fully mitigated by strict `.gitignore` and protected paths hooks |
| **TMMS-WEB** | Hardcoded Compose Password | 1 | `docker-compose.yml` (`POSTGRES_PASSWORD: tmms`) | Docker compose rewritten using OpenBao / env references |
| **TMMS-WEB** | **Total Findings** | **0** (Code/Config) | No private keys or bearer tokens discovered | Verified clean baseline |
