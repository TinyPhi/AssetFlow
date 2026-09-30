<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# Sample Organization Data Plan & Specification

**Document:** `docs/specs/sample-organization.md`  
**Task:** P4-03 (Gate G0.7 / Milestone M2.4-T2 / Master Plan §B14.1, Decision 38, Decision 4)  
**Target Commands:** `make demo-data` (seeder) and `make demo-data-remove` (purger)  
**Implementation Script:** `scripts/demo-data.py` (§B4.3, §B14.1)  
**Safety Guard:** Boot and execution strictly refused in production (`platform.env=production`).  
**Rule:** Zero real company names, real personal identities, real emails, brands, or production SQL dumps (§B14.1, Decision 41).

---

## 1. Objectives & Decision 38 Lifecycle

The Sample Organization data set serves four critical roles in AssetFlow (Decision 38):
1. **Developer Quickstart & Walkthrough:** Loaded by default in local development and quick-start profiles (`make bootstrap`) so developers encounter a working instance immediately.
2. **Sample Data Identification:** Every sample record is tagged with an `is_sample: true` metadata flag; the web UI displays a non-intrusive banner indicating sample data is active.
3. **Behavior & Parity Checklist Verification (Gate G2):** Systematic validation that all AssetManager & TMMS capabilities work against known sample records.
4. **Disaster Recovery Restore Verification (§B13.5):** Monthly automated backup-and-restore drills verify data integrity by decrypting and checking sample records.
5. **Load & Stress Testing Baseline (M2.4-T4, §B13.3):** The seeder supports `--scale N` (e.g. `--scale 10` for 750 assets, `--scale 100` for 7,500 assets) for k6 latency and connection pool benchmarks.

---

## 2. Strict Domain Neutrality & RFC 2606 Compliance

In accordance with §C1.2, Decision 4, and RFC 2606:
- **Company Identity:** Single consistent fictitious entity: **Sample Organization** (identifier: `0192f000-0000-7000-8000-000000000001`, slug: `sample`).
- **Domain & Email:** Strictly uses RFC 2606 reserved domains: `@example.com` and `.test`.
- **Personal Identifiers:** Neutral synthetic designations: `Member 01` through `Member 12`.
- **Equipment & Model Identifiers:** Neutral functional designations: `Workstation Model A`, `Network Switch S-48`, `Generator G-250`, `Centrifugal Pump P-100`, `Display D-27`. No commercial vendor brand names.
- **Physical Locations:** Generic architectural designations (`Site 1`, `Building A`, `Floor 2`, `Room 201`).
- **Phone Numbers:** Fictitious numbers reserved by telephony standards (`+1-555-0100` through `+1-555-0199`).

---

## 3. Provenance & "Derived From" Mapping

The sample dataset structure is derived from concepts in earlier test fixtures (`Server/scripts/pg_seed_dummy.py` and `Server/scripts/import_v2_from_sheet.py`), with all proprietary names, individual identities, and schema specifics removed:

| AssetFlow Sample Concept | Derived From (Old Source) | Cleanroom Transformation |
| :--- | :--- | :--- |
| Org Units Tree (`org_units`) | Hardcoded unit strings in `pg_seed_dummy.py` | Transformed into PostgreSQL `ltree` hierarchy (`sample.ops`, `sample.eng`, `sample.admin`). |
| Locations Tree (`locations`) | Flat address strings in `import_v2_from_sheet.py` | Transformed into hierarchical `ltree` locations (`sample.site1.bld_a...`). |
| Members & Grants (12 rows) | Flat roster table in `pg_seed_dummy.py` | Transformed into scoped RBAC roles (`admin`, `asset_manager`, `technician`, etc.). |
| Asset Catalog (75 assets) | Test asset list in `pg_seed_dummy.py` | Replaced brands with generic models; mapped to domain template keys. |
| Custody Assignments | `assignments` table in `pg_seed_dummy.py` | Mapped to polymorphic holder model (member, team, location) with versioning. |
| QR Code Batches | `qr_batches` in `pg_seed_dummy.py` | Pre-generated 128-bit SHA-256 capability tokens for scan testing. |

---

## 4. Entity Hierarchy & Target Record Counts

### 4.1 Organization & Domain Configuration
- **Name:** `Sample Organization`
- **Slug:** `sample`
- **Domain Key:** `it-assets` (with maintenance module installed)
- **Timezone:** `UTC`
- **Currency:** `USD` (`$`)

### 4.2 Organizational Units Tree (`org_units`) — Total: 7 Org Units
Structured hierarchical tree using PostgreSQL `ltree`:
- `Sample Organization` (root: `sample`)
  - `Operations` (`sample.ops`)
    - `Plant Maintenance` (`sample.ops.maint`)
    - `Facilities` (`sample.ops.fac`)
  - `Engineering` (`sample.eng`)
    - `IT Operations` (`sample.eng.it`)
    - `Systems` (`sample.eng.sys`)
  - `Administration` (`sample.admin`)
    - `Finance` (`sample.admin.fin`)
    - `People Operations` (`sample.admin.people`)

### 4.3 Locations Tree (`locations`) — Total: 8 Locations
Structured hierarchical physical locations using PostgreSQL `ltree`:
- `Site 1` (`sample.site1`)
  - `Building A` (`sample.site1.bld_a`)
    - `Floor 1` (`sample.site1.bld_a.fl1`)
      - `Workshop Room 101` (`sample.site1.bld_a.fl1.r101`)
    - `Floor 2` (`sample.site1.bld_a.fl2`)
      - `Server Room 201` (`sample.site1.bld_a.fl2.r201`)
  - `Building B` (`sample.site1.bld_b`)
    - `Plant Floor` (`sample.site1.bld_b.plant`)
    - `Storage Yard` (`sample.site1.bld_b.yard`)

### 4.4 Teams (`teams`) — Total: 3 Teams
- `IT Service Desk` (`team-it-service`, owning org unit: `sample.eng.it`)
- `Maintenance Crew` (`team-maint-crew`, owning org unit: `sample.ops.maint`)
- `Facilities Crew` (`team-fac-crew`, owning org unit: `sample.ops.fac`)

### 4.5 Members & Role Matrix (`members`, `role_grants`) — Total: 12 Members

| Member Identifier | Email | Primary Org Unit | Role Grant | Scope Level |
| :--- | :--- | :--- | :--- | :--- |
| **Member 01** | `member01@example.com` | Administration | `admin` | Organization (`sample`) |
| **Member 02** | `member02@example.com` | IT Operations | `asset_manager` | Branch (`sample.eng`) |
| **Member 03** | `member03@example.com` | Plant Maintenance | `planner` | Branch (`sample.ops`) |
| **Member 04** | `member04@example.com` | IT Operations | `team_lead` | Team (`IT Service Desk`) |
| **Member 05** | `member05@example.com` | Plant Maintenance | `technician` | Team (`Maintenance Crew`) |
| **Member 06** | `member06@example.com` | Facilities | `technician` | Team (`Facilities Crew`) |
| **Member 07** | `member07@example.com` | Operations | `org_unit_manager` | Branch (`sample.ops`) |
| **Member 08** | `member08@example.com` | Systems | `member` | Self (`Member 08`) |
| **Member 09** | `member09@example.com` | Finance | `member` | Self (`Member 09`) |
| **Member 10** | `member10@example.com` | People Operations | `member` | Self (`Member 10`) |
| **Member 11** | `member11@example.com` | Plant Maintenance | `member` | Self (`Member 11`) |
| **Member 12** | `member12@example.com` | Administration | `member` | Self (`Member 12`) |

### 4.6 Asset Catalog (`assets`) — Total: 75 Assets

Categories use domain template configuration keys (`config/domains/`):

| Category Key | Count | Neutral Model / Criticality | Custom Fields Seeded | Typical Status Breakdown |
| :--- | :---: | :--- | :--- | :--- |
| `workstations` | 35 | Workstation Model A / Model B (Medium Criticality) | `ram_gb: 32`, `os: Linux / Generic`, `storage: 1TB` | 26 assigned, 5 in stock, 2 in repair, 2 retired |
| `network_equipment` | 10 | Network Switch S-48, Gateway GW-10 (High Criticality) | `port_count: 48`, `firmware: v2.4`, `ip_address: 10.0.1.1` (Encrypted) | 8 in service, 2 in stock |
| `generators` | 5 | Generator G-250 Standby (Critical) | `power_kva: 250`, `fuel_type: Diesel`, `phase: 3` | 4 assigned to Plant Floor, 1 under maintenance |
| `pumps` | 15 | Centrifugal Pump P-100, Pump P-200 (High Criticality) | `flow_rate_m3h: 50`, `head_m: 80`, `motor_kw: 11` | 12 assigned to locations, 3 in repair |
| `displays` | 10 | Display D-27 High-Res (Low Criticality) | `resolution: 4K`, `panel_type: IPS` | 8 assigned, 2 in stock |

### 4.7 Custody & QR Code Infrastructure
- **Active Assignments:** 58 assigned assets linked to members, teams, and locations.
- **Pending Acknowledgements:** 4 assignments pending confirmation (triggers reminder sweeps in tests).
- **Custody History:** Over 80 historical assignment/return transaction records.
- **QR Batches (`qr_batches`):**
  - `Batch 2026-A`: 100 generated labels (50 consumed, 50 unassigned tag reservations).
  - `Batch 2026-B`: 50 reserved offline labels for upcoming equipment arrivals.

---

## 5. Explicit Purge Order & Audit Isolation

When running `make demo-data-remove` or invoking `scripts/demo-data.py --remove`:
1. **Safety Pre-check:** Confirms `slug == 'sample'` and `organization_id == '0192f000-0000-7000-8000-000000000001'`. The script strictly refuses to purge any other organization.
2. **Ordered Cascading Deletion:** Records are deleted in reverse dependency order within a single transaction:
   - `work_order_tasks` &rarr; `work_orders` &rarr; `work_requests`
   - `maintenance_schedules` &rarr; `maintenance_plans`
   - `asset_assignments` &rarr; `asset_components` &rarr; `assets`
   - `qr_batches` & `scan_events`
   - `team_members` &rarr; `teams`
   - `role_grants` &rarr; `member_org_units` &rarr; `members`
   - `locations` &rarr; `org_units`
   - `organization_modules` &rarr; `organizations`
3. **Audit Partition Handling:**
   - Sample audit records carry `organization_id = '0192f000-0000-7000-8000-000000000001'`.
   - The purge routine deletes sample audit rows via `DELETE FROM audit_events WHERE organization_id = '0192f000-0000-7000-8000-000000000001'`. `audit_events` is insert-only for the application roles (master plan §B10), so this statement runs only through the maintenance path under the migrator role (`assetflow_migrator`), never from the API or worker. Since the audit store is partitioned by month without foreign keys pointing inward, purging sample audit rows leaves real tenant audit logs completely unaffected.
