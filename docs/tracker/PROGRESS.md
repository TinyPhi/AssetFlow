# Progress Log

Record of completed tasks, tools, and milestone verifications.

## Toolchain Baseline (P0-01)
- Git: `2.53.0.windows.2`
- Python: `3.12.5`
- uv: `0.11.5`
- Node.js: `v24.14.1`
- Docker: `29.6.1`

## Log Entries

### 2026-09-29 — P0-01 Local workspace and git
- **Task:** P0-01
- **What changed:** Initialized git repo connected to `https://github.com/bikash-barnwal/AssetFlow.git`, committed initial skeleton on `main`, created working branch `chore/P0-local-setup`, verified `.claude` hooks and test suite.
- **Evidence:** Clean git working tree, `python .claude/hooks/af.py status` operational, 25/25 hook tests passed in pytest.
- **Next step:** P0-02 (Old code test baseline).

### 2026-09-29 — P0-02 Old-code test baseline
- **Task:** P0-02
- **What changed:** Re-measured AssetManager test suites; ran backend unit tests with coverage, ran frontend Vitest suite, cataloged Playwright specs and un-tested features in `docs/tracker/baseline-assetmanager.md`.
- **Evidence:** Backend: 323 passed, 5 skipped (328 tests), 44% line coverage. Frontend Vitest: 164 passed across 18 files. Playwright: 17 specs across 8 files.
- **Next step:** P0-03 (License, provenance and sensitive-file scan).

### 2026-09-29 — P0-03 License, provenance and sensitive-file scan
- **Task:** P0-03
- **What changed:** Audited dependency licenses across Python and Node.js, cataloged bundled static assets/branding for replacement, documented NEVER COPY operational sensitive paths, and completed secret pattern scan.
- **Evidence:** `docs/provenance-scan.md` created with dependency, asset, sensitive-file, and secret finding tables (12 findings in assetmanager, 0 in TMMS-WEB, secret values suppressed).
- **Next step:** P0-04 (Domain-term inventory).

### 2026-09-29 — P0-04 Domain-term inventory
- **Task:** P0-04
- **What changed:** Scanned legacy codebases for single-tenant, proprietary, and industry terms; cataloged 1,898 occurrences across 140+ files; mapped each term to its neutral AssetFlow replacement in `docs/tracker/domain-terms.md`.
- **Evidence:** `docs/tracker/domain-terms.md` created with hit counts and replacement mapping (employee → member, department → org unit, authnexus → auth provider, it_ops → operator, jmv → assetflow).
- **Next step:** P0-05 (Repo tracker in loop format).
