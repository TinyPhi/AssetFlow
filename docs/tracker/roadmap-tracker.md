# AssetFlow Roadmap Tracker

Single source of truth for the local delivery loop. Read by `af.py next-task`.
Status marks: `☐` not started · `◐` in progress · `☑` done · `⛔` blocked.

## P0 — Local Preparation

| ID | Task | Done when | Status |
| --- | --- | --- | --- |
| P0-01 | Local workspace and git (no GitHub) | Local repo exists on main, no remote, hooks run | ☑ |
| P0-02 | Old-code test baseline | Real numbers recorded (answers master-plan Q18) | ☑ |
| P0-03 | License, provenance and sensitive-file scan | Scan report lists every incompatible and sensitive item with a replace/never-copy decision | ☑ |
| P0-04 | Domain-term inventory | Denylist with replacements exists and covers every term found | ☑ |
| P0-05 | Repo tracker in loop format | af.py next-task prints a draft plan for the next open row | ☑ |

## P1 — Folder Skeleton and Governance Files (Milestone M1.1)

| ID | Task | Done when | Status |
| --- | --- | --- | --- |
| P1-01 | Folder layout from §B4.3 and §C7.1 | Tree matches §B4.3 and §C7.1 exactly | ☑ |
| P1-02 | License update (Apache-2.0 → AGPL-3.0-only), CLA, REUSE | LICENSE is AGPL-3.0; no Apache text left; reuse lint passes | ☑ |
| P1-03 | Project docs | Each file matches its plan section | ☑ |
| P1-04 | .github files (written, not pushed) | Files exist and match §B12.7 and §C5.8 | ☑ |
| P1-05 | ADRs 0001–0018 | 18 ADRs, status accepted | ☑ |
| P1-06 | Provenance record | Every §B14 row has a provenance entry (status: planned) | ☑ |

## P2 — Tooling and Local CI (Milestone M1.2)

| ID | Task | Done when | Status |
| --- | --- | --- | --- |
| P2-01 | Backend project | uv run pytest and uv run mypy app pass on the skeleton | ☑ |
| P2-02 | Frontend project | npm run build and npm test pass | ☑ |
| P2-03 | Makefile (single entry point) | make verify passes on the skeleton | ☑ |
| P2-04 | Check scripts | Each script fails on a bad sample and passes on the skeleton | ☑ |
| P2-05 | Pre-commit and local secret scan | Hooks run on a local commit | ☑ |
| P2-06 | CI workflow files (dormant) | Every workflow parses (actionlint) and each job maps to a make target | ☑ |

## P2b — Identity and secrets foundation: Zitadel and OpenBao as config (before P3)

| ID | Task | Done when | Status |
| --- | --- | --- | --- |
| P2-07 | OpenBao server from config | OpenBao starts from the HCL config, initializes, unseals by the runbook and reports healthy. | ☑ |
| P2-08 | OpenBao as code: engines, policies, AppRole | A second `make openbao-apply` reports no changes; each AppRole can read only its own paths. | ☑ |
| P2-09 | Zitadel self-hosted (official compose) | Zitadel console reachable at the configured domain; credentials came only from OpenBao. | ☑ |
| P2-10 | Zitadel as code: project, roles, apps | A second `make zitadel-apply` reports no changes; a test sign-in gets a JWT with project roles. | ☑ |
| P2-11 | Multi-organization in Zitadel | Two orgs from config; each signs in only to its own AssetFlow organization. | ☑ |
| P2-12 | Startup wiring and smoke test | Smoke test passes from a clean machine; a sealed OpenBao stops AssetFlow with a clear error. | ☑ |

## P3 — Bootable Backend, Web Shell and Minimal Stack (Parts of M1.3, M1.6)

| ID | Task | Done when | Status |
| --- | --- | --- | --- |
| P3-01 | Config loader | Invalid config stops boot with an exact path; tests cover it | ☑ |
| P3-02 | Database access and first migration | Migration check passes; isolation test passes; upgrade->downgrade->upgrade works | ☑ |
| P3-03 | Errors, envelope, IDs | Every error class maps to a code in the generated reference | ☑ |
| P3-04 | Provider interfaces and registry | A dummy provider is selected by config; contract test skeleton runs | ☑ |
| P3-05 | App factory and health | API starts locally and health returns every provider's state | ☑ |
| P3-06 | Web shell and compose.minimal | make up-minimal shows the web shell calling the health API | ◐ |

## P4 — Port Inventory for Master Phase 2

| ID | Task | Done when | Status |
| --- | --- | --- | --- |
| P4-01 | AssetManager port map | No old source file is unmapped | ☐ |
| P4-02 | TMMS vision capture | Notes ready for the M3.0 brief | ☐ |
| P4-03 | Sample organization data plan | Spec ready for M2.4-T2 | ☐ |

Phases P5 to P20 cover master milestones M1.4 to M4.3 and Gates G1 to G6. Each row is one small plan with its own issue; the epic issue lists them in run order. Rows run in the order shown.

## P5 — Organization structure and access (master M1.4) — epic #19

| ID | Task | Issue | Done when | Status |
| --- | --- | --- | --- | --- |
| P5-00 | Database login naming and role standard | #21 (PR #20) | Searching the repo finds no `assetflow_*_user` login name; `make up-minimal` starts healthy with the `_login` users; the naming test passes; the ADR is accepted | ◐ |
| P5-01 | Organization structure migrations | #22 (PRs #36–#39) | `scripts/check-migrations.py` passes; upgrade, downgrade, upgrade works; every new table has an isolation test proving another organization's rows are invisible and not writable | ◐ |
| P5-08 | Audit store (run second, before any write feature) | #23 (PR #47) | A privilege test shows UPDATE and DELETE on audit events fail for every application role; events land in the right monthly partition; the audit API returns only the caller's scope | ◐ |
| P5-02 | `assetflow org create` command | #24 (PR #48) | A new organization and its invited first admin exist after one command; a second run changes nothing | ◐ |
| P5-03 | Member provisioning policies | #25 (PR #49) | API end-to-end sign-in tests cover each policy, unknown organizations and suspension | ◐ |
| P5-04 | Org unit, location and team management | #26 (PR #50) | Moving an org unit updates the paths of everything under it; blocking rules are enforced and tested | ◐ |
| P5-05 | Scoped role grants | #27 (PR #51) | Scope-leakage tests pass, including revoked access stopping immediately | ◐ |
| P5-06 | Module installation from domain templates | #28 (PR #52) | Routes answer `module.not_installed` before installation and work after it | ◐ |
| P5-07 | Bulk import of org units, teams and members | #29 (PR #53) | Import is all or nothing, with a preview that writes nothing | ◐ |
| P5-09 | Organization settings API | #30 (PR #54) | Settings changes are audited | ◐ |
| P5-10 | Acceptance, docs and evidence for M1.4 | #31 (PR #55) | The tenant-isolation suite (tables, views, repositories, endpoints, worker) and the scope-leakage suite pass; docs and evidence exist | ◐ |

## P6 — Notifications and worker (master M1.5) — epic #58

| ID | Task | Issue | Done when | Status |
| --- | --- | --- | --- | --- |
| P6-01a | Worker process and outbox dispatcher | #59 (PRs #209–#211) | Worker isolation tests pass; claiming with `SKIP LOCKED`, 5-minute reclaim, dead letter, exactly one effect after a kill mid-batch | ◐ |
| P6-01b | Job runner and housekeeping | #60 | Worker isolation tests pass for jobs and housekeeping; 7-day cleanup per organization; time limits enforced | ☐ |
| P6-00 | Notification tables migration | #61 | Migration check passes; upgrade → downgrade → upgrade works; isolation tests for all four tables | ☐ |
| P6-02 | Automation engine basics: event → recipients → channels | #62 | Unit tests for recipient resolution pass | ☐ |
| P6-03 | In-app channel and inbox API | #63 | Inbox API E2E tests pass | ☐ |
| P6-06a | Channel runtime: encrypted credentials and egress allowlist | #64 | Channel contract suite passes for schema, write-only secrets, egress (incl. re-resolve to 127.0.0.1) and health | ☐ |
| P6-06b | Notification sender: retries, dead letter, idempotency, delivery log | #65 | Channel contract suite passes incl. retries and idempotency; 3 attempts → dead letter → admin alert; kill switch stops sends | ☐ |
| P6-06c | Channel installations API, kill switch and delivery log API | #66 | Secrets write-only; kill switch instant; delivery log lists every attempt | ☐ |
| P6-04 | Email channel | #67 | Emails arrive in Mailpit | ☐ |
| P6-05 | Webhook channel | #68 | A signed request with the mapped fields is received by a test endpoint | ☐ |
| P6-07 | Member notification preferences | #69 | Preferences change which channels are used | ☐ |
| P6-08 | Channel settings schemas as JSON Schema | #70 | Schema endpoint returns each channel's schema; secrets are write-only | ☐ |
| P6-09 | Acceptance, docs and evidence for M1.5 | #71 | One event → in-app + email + signed webhook, all logged; failing SMTP → retries → dead letter → admin alert; docs and evidence exist | ☐ |

## P7 — Web shell and deployment (master M1.6) + Gate G1 — epic #72

| ID | Task | Issue | Done when | Status |
| --- | --- | --- | --- | --- |
| P7-01 | Frontend foundation: themes, routing, permission-aware navigation | #73 | Theme-regression source scan passes; nav follows permissions and installed modules | ☐ |
| P7-03 | Translation setup and locale formatting | #74 | No raw UI text in components (CI check) | ☐ |
| P7-07a | Hardened nginx: headers and rate limits | #75 | Every §C5.10 header on every response; rate-limit zones answer 429; ZAP baseline passes | ☐ |
| P7-07b | Container hardening and the complete full profile | #76 | Containers run as non-root with read-only filesystems (both profiles); full profile healthy | ☐ |
| P7-02a | BFF session endpoints | #77 | Session, refresh rotation, logout, policy E2E tests pass (mock; oidc recorded) | ☐ |
| P7-02b | Frontend sign-in, idle logout, not-authorized screen | #78 | Sign-in flows work in both profiles | ☐ |
| P7-04a | Screen APIs: members, profile, access view, modules | #79 | Every screen has a documented endpoint; "Org structure and access" API E2E passes | ☐ |
| P7-04b | Screens: dashboard shell, org chart, locations | #80 | Screens pass the release-checklist widths | ☐ |
| P7-04c | Screens: teams, members, member profile | #81 | Screens pass the release-checklist widths | ☐ |
| P7-04d | Screens: access view, modules, organization settings | #82 | Screens pass the release-checklist widths | ☐ |
| P7-05 | Notification bell, inbox and preferences | #83 | Works with the M1.5 APIs | ☐ |
| P7-06 | Admin forms generated from schemas | #84 | Adding a schema field shows up in the form with no UI code | ☐ |
| P7-10 | Authorization-matrix tests | #85 | Every route × role meets its expectation; an undeclared route fails the build | ☐ |
| P7-08 | Bootstrap scripts, both profiles | #86 | A clean machine reaches a working sign-in with one command, in both profiles | ☐ |
| P7-09a | Backup service (pgBackRest) and alerts | #87 | Encrypted full/diff/WAL backups off-site with a write-once copy; verify passes; four alerts fire | ☐ |
| P7-09b | `make restore` and the monthly restore test | #88 | A restore onto a fresh machine passes: keys restored, sample field decrypted, smoke and isolation tests green | ☐ |
| P7-11 | OWASP ASVS 5.0 Level 2 checklist file | #89 | The checklist file exists with every requirement listed; CI catches drift | ☐ |
| P7-12 | Acceptance, Gate G1, docs and evidence | #90 | Every Gate G1 criterion passes with evidence; demo of both profiles recorded; docs written | ☐ |

## P8 — Asset data and catalog (master M2.1) — epic #91

| ID | Task | Issue | Done when | Status |
| --- | --- | --- | --- | --- |
| P8-01 | Domain template asset sections (`it-assets`, `facilities`) | #92 | Both templates load and validate; asset rules come from the template, not code | ☐ |
| P8-02 | Catalog migrations a: categories, custom field definitions, manufacturers, suppliers | #93 | Migration check and isolation tests pass | ☐ |
| P8-03 | Catalog migrations b: assets, components, meters, readings, indexes, views | #94 | Migration check and isolation tests pass; path trigger and index use proven | ☐ |
| P8-04 | Custom field validation and encrypted fields | #95 | Unit tests for every field type; encrypted values never appear in list responses | ☐ |
| P8-05 | Asset tag generation per organization | #96 | Tags are unique per organization | ☐ |
| P8-06 | Catalog reference data API and template seed | #97 | Reference data managed with audit; seed idempotent | ☐ |
| P8-07 | Asset API: create, edit, detail, list, saved views | #98 | Scoped CRUD and list with search, filters, saved views, sort, cursor | ☐ |
| P8-08 | Lifecycle statuses and transitions | #99 | Invalid transitions are refused with a clear error | ☐ |
| P8-09 | Components (move together) | #100 | API E2E test passes | ☐ |
| P8-10 | Asset list screen | #101 | Screen works at every checklist width | ☐ |
| P8-11 | Asset detail, create/edit and category admin screens | #102 | Screens work at every checklist width | ☐ |
| P8-12 | Acceptance, docs and evidence for M2.1 | #103 | AssetManager's catalog features in §B15 pass; docs and evidence exist | ☐ |

## P9 — Custody and QR (master M2.2) — epic #104

| ID | Task | Issue | Done when | Status |
| --- | --- | --- | --- | --- |
| P9-01 | Custody and QR migrations | #105 | Migration check and isolation tests pass; one open assignment per asset enforced | ☐ |
| P9-02 | Assign, transfer and return | #106 | Custody API E2E flow passes | ☐ |
| P9-03 | Holder can be a member, a team or a location | #107 | Tests cover each holder type | ☐ |
| P9-04 | Owner follows holder, audited cascade | #108 | Test confirms the owner org unit change and its audit event | ☐ |
| P9-05 | Acknowledgement, reminder, escalation, automatic closing | #109 | Worker tests cover each step, exactly once | ☐ |
| P9-06 | Receipt and return PDFs (PDF engine) | #110 | PDF snapshot tests pass | ☐ |
| P9-07 | QR batches, reserved tags, create from a reserved tag | #111 | Reserved-tag flow test passes | ☐ |
| P9-08 | Label PDF and unused-tag PDF | #112 | Labels decode to active tokens; regenerating revokes old tokens | ☐ |
| P9-09 | Scan tokens, signed-in scan, public scan | #113 | Public scan never returns other fields (test) | ☐ |
| P9-10 | "Report a problem" from the public page | #114 | Abuse tests pass | ☐ |
| P9-11 | Custody screens | #115 | UF4 works in the browser at every checklist width | ☐ |
| P9-12 | QR labels, signed-in scan and public scan screens | #116 | UF3 labels path and UF5 work in the browser at every width | ☐ |
| P9-13 | Acceptance, docs and evidence for M2.2 | #117 | UF3, UF4 and UF5 work end to end; guides and security notes exist | ☐ |

## P10 — Import, export, audit, dashboards (master M2.3) — epic #118

| ID | Task | Issue | Done when | Status |
| --- | --- | --- | --- | --- |
| P10-01 | Bulk import a: upload, safe parsing, preview in the worker | #119 | Preview reports every row error, writes nothing; bad files refused | ☐ |
| P10-02 | Bulk import b: all-or-nothing apply and import screen | #120 | Import API E2E tests, including bad files | ☐ |
| P10-03 | Exports with formula protection; worker exports with expiry | #121 | Cells beginning with `=`, `+`, `-` or `@` are neutralized (test) | ☐ |
| P10-04 | Asset timeline and organization audit view | #122 | Every asset action appears in the timeline | ☐ |
| P10-05 | Audit PDFs: asset history and audit trail | #123 | PDF snapshot tests pass; large PDFs in the worker | ☐ |
| P10-06 | Warranty alerts through automations | #124 | Alerts fire at the configured days, once each | ☐ |
| P10-07 | Dashboards API (organization, org unit, team, personal) | #125 | Figures match the member's scope (tests) | ☐ |
| P10-08 | Dashboard screens | #126 | Dashboards render scoped figures at every checklist width | ☐ |
| P10-09 | Member avatars | #127 | Upload and rejection tests pass | ☐ |
| P10-10 | Acceptance, docs and evidence for M2.3 | #128 | §B15 import, export, audit and dashboard features pass; guides exist | ☐ |

## P11 — AssetManager parity check (master M2.4) and Gate G2 — epic #129

| ID | Task | Issue | Done when | Status |
| --- | --- | --- | --- | --- |
| P11-01 | AssetManager behavior checklist | #130 | Checklist committed to `docs/specs/` | ☐ |
| P11-02 | Sample organization: `make demo-data` / `demo-data-remove` | #131 | `make demo-data` loads it, and `make demo-data-remove` deletes it | ☐ |
| P11-03 | Run the checklist on the sample organization | #132 | Every item passes, or has an issue with a fix planned before Gate G2 | ☐ |
| P11-04 | Scaled data for the load test and the restore test | #133 | Both use the same generated data set | ☐ |
| P11-05 | First load test on the asset endpoints | #134 | Load test run and recorded; any miss has an issue | ☐ |
| P11-06 | Gate G2 check, M2.4 docs and evidence | #135 | Every Gate G2 criterion has recorded evidence; tutorial and feature mapping written | ☐ |

## P12 — Maintenance brief and spec (master M3.0) + Gate G3 — epic #136

| ID | Task | Issue | Done when | Status |
| --- | --- | --- | --- | --- |
| P12-01 | One-page maintenance brief (owner-written) | #137 | Brief committed to `docs/specs/` | ☐ |
| P12-02 | Maintenance engine spec `docs/specs/maintenance-engine.md` | #138 | Spec follows §C6.6 template and is approved by the requirements owner | ☐ |
| P12-03 | Rail-maintenance and facilities domain templates (draft) | #139 | Both templates validate | ☐ |
| P12-04 | Independent validation by a maintenance practitioner | #140 | Their comments are resolved and recorded | ☐ |
| P12-05 | Check the spec against the brief; resolve every open point; approval | #141 | Spec approved and recorded → Gate G3 | ☐ |
| P12-06 | Maintenance behavior checklist | #142 | Checklist committed to `docs/specs/`; Gate G4 needs it to pass | ☐ |
| P12-07 | Acceptance and Gate G3 record | #143 | Spec approved by the requirements owner and recorded → | ☐ |

## P13 — Workflow and automation engines (master M3.1) — epic #144

| ID | Task | Issue | Done when | Status |
| --- | --- | --- | --- | --- |
| P13-01 | Workflow engine | #145 | Unit tests cover every transition in each domain template | ☐ |
| P13-02 | Automation engine (extends the M1.5-T2 basics) | #146 | Unit tests for every operator and action | ☐ |
| P13-03 | Config validation for workflows and automations | #147 | Invalid templates stop the boot with exact paths | ☐ |
| P13-04 | Acceptance, docs and evidence for M3.1 | #148 | Engine unit tests cover every transition and condition operator | ☐ |

## P14 — Requests and work orders (master M3.2) — epic #149

| ID | Task | Issue | Done when | Status |
| --- | --- | --- | --- | --- |
| P14-01 | Migrations: work requests, work orders, tasks, transitions, downtime, SLA events | #150 | Migration check and isolation tests pass | ☐ |
| P14-03 | Work orders with priority from the matrix plus criticality; override with a reason | #151 | Priority table tests pass | ☐ |
| P14-02 | Work requests (members and public reports) and triage | #152 | UF6 triage paths pass | ☐ |
| P14-04 | Checklist tasks, readings, notes; failed high-severity task → follow-up work order | #153 | Automation test passes | ☐ |
| P14-05 | Asset status link and downtime | #154 | Cross-module event tests pass | ☐ |
| P14-06 | Work request and work order screens | #155 | Screens pass the checklist widths | ☐ |
| P14-07 | Acceptance, docs and evidence for M3.2 | #156 | Request-to-completion API E2E flow passes | ☐ |

## P15 — Preventive planning (master M3.3) — epic #157

| ID | Task | Issue | Done when | Status |
| --- | --- | --- | --- | --- |
| P15-01 | Maintenance plans | #158 | Plan API tests pass | ☐ |
| P15-02 | Schedules and schedule rules | #159 | Schedule rule tests pass | ☐ |
| P15-03 | Schedule evaluator in the worker | #160 | One work order per due period, across restarts and with two workers | ☐ |
| P15-04 | Plans, schedules and calendar screens | #161 | Screens pass the checklist widths | ☐ |
| P15-05 | Acceptance and evidence for M3.3 | #162 | Exactly one work order per due period, across restarts and with two workers; the preventive-schedule API E2E flow (§C8.6) passes | ☐ |

## P16 — SLA and escalation (master M3.4) — epic #163

| ID | Task | Issue | Done when | Status |
| --- | --- | --- | --- | --- |
| P16-01 | Working calendars: maths, API, assignment (two parts) | #164 | Calendar maths tests pass | ☐ |
| P16-02 | SLA clocks with pause and precomputed times | #165 | Unit tests with frozen time | ☐ |
| P16-03 | SLA sweeper | #166 | Worker tests pass | ☐ |
| P16-04 | Two-level escalation; due-soon and overdue notices | #167 | Notifications reach the right people (tests) | ☐ |
| P16-05 | Acceptance and evidence for M3.4 | #168 | Warnings and breaches fire exactly once, respecting calendars and pauses; the §C8.6 SLA E2E flow passes | ☐ |

## P17 — Dispatch, views, KPIs (master M3.5) + Phase 3 docs + Gate G4 — epic #169

| ID | Task | Issue | Done when | Status |
| --- | --- | --- | --- | --- |
| P17-01 | Routing rules | #170 | Routing tests pass | ☐ |
| P17-02 | Dispatch board, team workload, bulk dispatch, audited reassignment (two parts) | #171 | Dispatch API E2E flow passes | ☐ |
| P17-03 | Kanban board, backlog view, calendar view | #172 | Screens pass the checklist widths | ☐ |
| P17-04 | Technician "my work" view for phones | #173 | Works at 320 px wide | ☐ |
| P17-05 | KPIs and exports (two parts) | #174 | Figures match test data | ☐ |
| P17-06 | Phase 3 docs: maintenance user, planner, technician guides; domain template guide | #175 | Every guide in the Phase 3 docs list exists, follows §C7.3 and passes `make docs-check` | ☐ |
| P17-07 | Acceptance for M3.5 and Gate G4 | #176 | A technician completes a work order end to end on a 320 px-wide phone screen; every Gate G4 criterion is checked and recorded | ☐ |

## P18 — Unified app and admin (master M4.1) — epic #177

| ID | Task | Issue | Done when | Status |
| --- | --- | --- | --- | --- |
| P18-01 | One navigation and the screen map | #178 | Every screen in §B4.8.3 is reachable | ☐ |
| P18-02 | Cross-module asset and work order pages | #179 | Cross-module screens tested | ☐ |
| P18-03a | Admin: provider and channel status, effective config | #180 | Status and effective-config screens work, with secrets hidden | ☐ |
| P18-03b | Admin: roles and grants, delivery log, audit and config history | #181 | The four screens work inside the caller's scope | ☐ |
| P18-03c | Admin guide written against the real screens | #182 | Admin guide written against the real screens | ☐ |
| P18-04 | Full release checklist run | #183 | All items pass, or known issues are listed | ☐ |
| P18-05 | Acceptance, no-raw-text check and evidence for M4.1 | #184 | Release checklist passes: all screen sizes, accessibility (WCAG 2.2 AA), supported browsers | ☐ |

## P19 — Security review and standards (master M4.2) — epic #185

| ID | Task | Issue | Done when | Status |
| --- | --- | --- | --- | --- |
| P19-01 | Complete the ASVS Level 2 checklist | #186 | No requirement left open | ☐ |
| P19-04 | Privacy compliance page (DPDP Act 2023 and GDPR) | #187 | Page in the docs | ☐ |
| P19-05 | Security-path approval rule and `SECURITY.md` live | #188 | Branch rules need the second reviewer's approval on security paths | ☐ |
| P19-06a | Scorecard and Best Practices self-assessments | #189 | Every Scorecard check and Best Practices "passing" criterion met or has a written reason | ☐ |
| P19-02 | Internal security review (prep, hand-off, record) | #190 | Findings recorded in `docs/reviews/` | ☐ |
| P19-03 | Fix every finding or record a risk decision | #191 | No Critical findings open; every open finding has a recorded decision | ☐ |
| P19-07 | Acceptance and evidence for M4.2 | #192 | Findings recorded in `docs/reviews/` and closed or accepted; self-assessments complete (badges follow in P19-06b) | ☐ |
| P19-06b | Badges published in the README | #193 | Badges shown in the README | ☐ |

## P20 — Docs, release pipeline, performance, Gate G5 and Gate G6 (master M4.3) — epic #194

| ID | Task | Issue | Done when | Status |
| --- | --- | --- | --- | --- |
| P20-01a | Generated reference pages and docs check | #195 | Generated reference pages current; `make docs-check` passes | ☐ |
| P20-01b | User guides and tutorials with the sample organization | #196 | User guide and tutorials complete, no broken links | ☐ |
| P20-01c | Admin, config, events, channel, provider and domain guides | #197 | Every guide in §C7.1 and §B12.10 exists, no broken links | ☐ |
| P20-01d | Operations runbooks | #198 | Every §B13.6 runbook exists, no broken links | ☐ |
| P20-01e | Feature mapping from AssetManager and TMMS | #199 | Every source feature maps to an AssetFlow screen or a recorded decision | ☐ |
| P20-02 | Release pipeline dry run | #200 | An operator's verification steps succeed on the dry-run images | ☐ |
| P20-03 | Load tests on the single-node and scaled setups | #201 | Results recorded; any misses have issues | ☐ |
| P20-04 | Upgrade test from the previous pre-release | #202 | Upgrade works with no manual steps beyond the release notes | ☐ |
| P20-06 | Disaster-recovery drill (M4.3-T6) | #203 | Measured RPO and RTO meet §B13.5; runbook updated | ☐ |
| P20-05 | Go-public checklist for the TinyPhi owners (M4.3-T5) | #204 | Checklist delivered | ☐ |
| P20-07 | Acceptance for M4.3, migration guide, good-first-issues list | #205 | A dry-run release verifies (signature, SBOM, provenance); docs build with no broken links | ☐ |
| P20-08 | Gate G5 — go public, criterion by criterion | #206 | Every G5 criterion checked with evidence | ☐ |
| P20-09 | Clean-clone 15-minute trial and third-party channel trial | #207 | Both trials pass and are recorded | ☐ |
| P20-10 | Gate G6 — release 1.0.0, criterion by criterion | #208 | Every G6 criterion checked with evidence; 1.0.0 hand-off ready | ☐ |
