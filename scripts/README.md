<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# `scripts`

Developer workflow scripts and CI checks (master plan §B10, §C3.2, §C9). Run them through `make`
(see `make help`); CI calls the same `make ci-*` targets.

Each check is a Python 3.10+ script (standard library only) with a `.sh` wrapper that finds a working
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
| `zitadel-apply.sh` | Zitadel project, roles and apps with OpenTofu (fails when neither `tofu` nor `terraform` is installed) | `make zitadel-apply`, `make up-full` |
| `smoke-full.sh` | Smoke test of the running full profile | `make smoke-full` |

Each check also takes file or directory paths, which is how the rules are tried against a bad sample.
