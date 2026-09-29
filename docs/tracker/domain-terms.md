# Domain Terms Denylist & Neutral Replacement Dictionary

**Date:** 2026-09-29  
**Source Code Inspected:** `individual-projects/assetmanager/` and `individual-projects/TMMS-WEB/`  
**Task:** P0-04 (Master Plan §C1.2, §B2.1, M1.2-T4)  
**Enforcement:** This dictionary forms the baseline denylist for `check-domain-terms.sh` and pre-commit hooks in Phase 2.

---

## 1. Executive Summary

AssetFlow is a generic, open-source multi-tenant asset and maintenance platform. Per **Master Plan Decision D8 and Section §C1.2**, the codebase must contain **zero industry-specific, company-specific, or single-tenant proprietary vocabulary in core logic**.

Industry concepts belong exclusively in declarative domain templates (`config/domains/*.yaml`), while organization identity belongs in configuration (`config/assetflow.yaml`).

A comprehensive static audit across `individual-projects/assetmanager/Server`, `individual-projects/assetmanager/Client/src`, and `individual-projects/TMMS-WEB` identified **1,898 total occurrences** of forbidden terms across **140+ files**.

---

## 2. Denylist Inventory & Neutral Replacement Mapping

| Forbidden Term | Category | Legacy Hit Count | Affected Files | Neutral Replacement in AssetFlow | Architectural Rationale & Reference |
| --- | --- | :---: | :---: | --- | --- |
| **`employee`** / **`employees`** | Organizational Model | **1,089** | 139 files (548 Server, 540 Client, 1 TMMS) | **`member`** / **`members`** (`User` in auth context) | Multi-tenant organizations include contractors, volunteers, and students. Scoped via `members` and `organization_id` (§B5.3). |
| **`department`** / **`departments`** | Organizational Model | **300** | 53 files (140 Server, 160 Client) | **`org_unit`** / **`organization_unit`** / **`team`** | Replaced with hierarchical organization units modeled via PostgreSQL `ltree` (§B5.4, §B10). |
| **`authnexus`** / **`auth_nexus`** | Proprietary Gateway | **220** | 67 files (169 Server, 48 Client, 3 TMMS) | **`auth_provider`** / **`oidc_provider`** (Zitadel preset) | Hardcoded identity gateway replaced by pluggable `AuthProvider` interface (Decision D3, §B6.1). |
| **`it_ops`** / **`it-ops`** | Hardcoded Role | **129** | 48 files (78 Server, 51 Client) | **`operator`** / **`technician`** / scoped permissions | Hardcoded roles replaced by fine-grained scoped RBAC (`ctx.scope.require`, Decision D4, §C5.4). |
| **`jmv`** | Company Identifier | **93** | 30 files (56 Server, 37 Client) | **`assetflow`** / **`org_default`** | Proprietary company acronym removed from asset tags, sequences, table defaults, and tokens. |
| **`laptop`** / **`laptops`** | Hardcoded Category | **50** | 17 files (11 Server, 39 Client) | Generic **`category`** / domain template key | Specific device types moved out of code into `config/domains/it-assets.yaml` (Decision D8, §B7). |
| **`rokkalabs`** | Company / Vendor | **9** | 5 files (3 Server, 2 Client, 1 TMMS) | **`provider_endpoint`** / configuration parameter | Proprietary domain and issuer names removed; configured via OpenBao / environment. |
| **`rail`** / **`railway`** | Industry Specific | **5** | 5 files (Client) | Move to `config/domains/railway.yaml` | Core platform is agnostic; industry vocabulary isolated in templates (§C1.2). |
| **`telecom`** | Industry Specific | **2** | 2 files (TMMS) | Move to `config/domains/telecom.yaml` | Replaced by neutral maintenance platform terminology. |
| **`train`** | Industry Specific | **1** | 1 file (Client) | Move to `config/domains/railway.yaml` | Industry asset model moved to domain config. |
| **`novu`** | Third-Party Service | *(Identified in docs/env)* | - | **`notification_channel`** / **`inapp_channel`** | Pluggable notification channel architecture (Decision D15, §B6.3). |

---

## 3. Enforcement Strategy (`check-domain-terms.sh`)

1. **Pre-Commit Enforcement**:
   - The shell script `scripts/check-domain-terms.sh` (built in Milestone M1.2 / P2-04) will run `ripgrep` against staged changes for the root patterns:
     ```bash
     \b(jmv|rokkalabs|auth_?nexus|novu|employees?|departments?|it[-_]ops|telecom|railway)\b
     ```
   - Matches outside of `config/domains/` or migration history will reject commits with exit code 1.

2. **Permitted Exceptions**:
   - `docs/tracker/domain-terms.md` (this inventory document).
   - Historical audit files explicitly marked in `docs/provenance-scan.md`.
   - Domain templates inside `config/domains/*.yaml` where industry terms are legitimately declared by end-user organizations.
