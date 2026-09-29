<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# `scripts`

Developer workflow scripts and CI checks (master plan §B10, §C3.2, §C9). Run them through `make`
(see `make help`); CI calls the same `make ci-*` targets.

Each check is a Python 3.10+ script (standard library only, except `bootstrap_zitadel.py`) with a `.sh` wrapper that finds a working
Python on Linux, macOS and Git Bash on Windows (set `PYTHON=...` to choose one). Exit code 0 means
pass, 1 means a rule was broken, 2 means the check could not run.

| Script | Rule | Called by |
| --- | --- | --- |
| `check-domain-terms.sh` | No word from `check-domain-terms.txt` (§C12, P0-04 inventory) in `backend/app/`, `frontend/src/` or `config/` (except `config/domains/` and `config/templates/`); case-insensitive, whole words; translation files excluded | `make lint`, pre-commit |
| `check-migrations.sh` | Tenant tables have `organization_id NOT NULL`, RLS `ENABLE` and `FORCE`, four fail-closed policies, an `organization_id`-first index; views are `security_invoker`; `SECURITY DEFINER` functions pin `search_path = pg_catalog, pg_temp` and revoke `EXECUTE` from `PUBLIC`. Exceptions are described in the script's docstring | `make lint` |
| `check-contribution-guardrails.sh` | PR rules of §C9.4: tests changed, isolation changed, forbidden files, ADR and issue links, PR size, template completed | `make ci-contribution-checks BASE=<sha>` (`contribution-checks.yml`) |
| `check-docs-links.sh` | No broken relative links in Markdown files | `make docs-check` |
| `check-licenses.sh` | Dependency licenses on the §C4.11 allowlist (pip-licenses for `backend/uv.lock`, license-checker for `frontend/node_modules`); copyleft always fails; other licenses fail for runtime dependencies unless recorded in `check-licenses-exceptions.txt` | `make license-check`, `make ci-license-check` |
| `openbao-apply.sh` | OpenBao engines, policies, AppRoles (`--generate-missing` first run, `--issue-secret-ids` start flow) | `make openbao-apply [GENERATE_MISSING=1] [ISSUE_SECRET_IDS=1]`, `make up-full` |
| `bootstrap.sh`, `bootstrap.ps1` (+ `setup.bat` in the root) | One-command identity setup with Docker only: `.env.local` secrets (development) or OpenBao (`ASSETFLOW_ENV=production`), Zitadel, bootstrap; `--dry-run`, `--reset` | `make bootstrap`, `setup.bat` |
| `bootstrap_zitadel.py` | Idempotent Zitadel bootstrap through the official APIs: project, roles, apps, machine users, one organization and project grant per `config/organizations/*.yaml`; results to `.env.local` or OpenBao. Not standard library only: its pinned dependencies are in its PEP 723 header; runs in `deploy/bootstrap/Dockerfile` or with `uv run` | `make zitadel-apply [DRY_RUN=1]`, `make up-full` |
| `tests/` | pytest suite of `bootstrap_zitadel.py` against a mocked Zitadel and OpenBao (`httpx.MockTransport`) | `make test-scripts` (part of `make ci-quality` and `make verify`) |
| `smoke-full.sh` | Smoke test of the running full profile | `make smoke-full` |

Each check also takes file or directory paths, which is how the rules are tried against a bad sample.
