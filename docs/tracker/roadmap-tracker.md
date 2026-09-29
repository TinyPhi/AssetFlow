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
| P1-01 | Folder layout from §B4.3 and §C7.1 | Tree matches §B4.3 and §C7.1 exactly | ☐ |
| P1-02 | License, CLA, REUSE | reuse lint passes | ☐ |
| P1-03 | Project docs | Each file matches its plan section | ☐ |
| P1-04 | .github files (written, not pushed) | Files exist and match §B12.7 and §C5.8 | ☐ |
| P1-05 | ADRs 0001–0018 | 18 ADRs, status accepted | ☐ |
| P1-06 | Provenance record | Every §B14 row has a provenance entry (status: planned) | ☐ |

## P2 — Tooling and Local CI (Milestone M1.2)

| ID | Task | Done when | Status |
| --- | --- | --- | --- |
| P2-01 | Backend project | uv run pytest and uv run mypy app pass on the skeleton | ☐ |
| P2-02 | Frontend project | npm run build and npm test pass | ☐ |
| P2-03 | Makefile (single entry point) | make verify passes on the skeleton | ☐ |
| P2-04 | Check scripts | Each script fails on a bad sample and passes on the skeleton | ☐ |
| P2-05 | Pre-commit and local secret scan | Hooks run on a local commit | ☐ |
| P2-06 | CI workflow files (dormant) | Every workflow parses (actionlint) and each job maps to a make target | ☐ |

## P3 — Bootable Backend, Web Shell and Minimal Stack (Parts of M1.3, M1.6)

| ID | Task | Done when | Status |
| --- | --- | --- | --- |
| P3-01 | Config loader | Invalid config stops boot with an exact path; tests cover it | ☐ |
| P3-02 | Database access and first migration | Migration check passes; isolation test passes; upgrade->downgrade->upgrade works | ☐ |
| P3-03 | Errors, envelope, IDs | Every error class maps to a code in the generated reference | ☐ |
| P3-04 | Provider interfaces and registry | A dummy provider is selected by config; contract test skeleton runs | ☐ |
| P3-05 | App factory and health | API starts locally and health returns every provider's state | ☐ |
| P3-06 | Web shell and compose.minimal | make up-minimal shows the web shell calling the health API | ☐ |

## P4 — Port Inventory for Master Phase 2

| ID | Task | Done when | Status |
| --- | --- | --- | --- |
| P4-01 | AssetManager port map | No old source file is unmapped | ☐ |
| P4-02 | TMMS vision capture | Notes ready for the M3.0 brief | ☐ |
| P4-03 | Sample organization data plan | Spec ready for M2.4-T2 | ☐ |
