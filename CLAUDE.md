# CLAUDE.md

Engineering conventions for AI-assisted work on AssetFlow. AI-generated code passes the same gates as any other code; the human author is responsible for it and must understand it (plan §B12.10).

## What AssetFlow is

- One open-source platform for **asset management** (from AssetManager) and **maintenance management** (the TMMS vision).
- **Generic**: no industry logic in code; each organization picks a domain template (`config/domains/*.yaml`).
- **Organization-ready**: many organizations per installation, isolated by PostgreSQL RLS; org units, teams, members and locations with scoped access.
- **Stack**: Python 3.12 / FastAPI modular monolith + React 19 SPA, PostgreSQL 16, separate worker; Zitadel, OpenBao, OpenTelemetry behind provider interfaces.
- **License**: AGPL-3.0 plus a commercial license from TinyPhi, with a CLA. Web only in 1.0, API-first (`/api/v1`).

The plan document is the source of truth: **`../Plan/OpenSource.AssetFlow.md`** until it is moved into `docs/`. Section references below (§B5.3, D4, ...) point into it. Settled decisions: §B3 (D1–D18) and §B17.

## Read before touching

| Area | Plan sections | Context file |
| --- | --- | --- |
| Tenancy, RLS, scopes, grants, org structure | D4, D7, D13, §B5, §B10, §C5.4, §C8.5 | `.claude/context/rls-and-scopes.md` |
| Outbox, events, worker jobs | D9, §B9.3, §B10, §C4.3 | `.claude/context/outbox-and-worker.md` |
| Providers, secrets, auth/session | D3, D11, D17, D18, §B6.1–§B6.2, §B11.2, §B11.4, §C5.5 | `.claude/context/providers-and-secrets.md` |
| Notifications and channels | D15, D17, §B6.3, §C6.7 | `.claude/context/notifications.md` |
| Maintenance, schedules, SLA, engines | D8, §B7.3, §B9 | `.claude/context/sla-and-maintenance.md` |
| Config and domain templates | D8, D12, §B5.9, §B7, §B12.2 | `.claude/context/config-and-domains.md` |
| Migrations and repositories | D5, D6, §C1.4, §C4.4, §C4.8 | `.claude/rules/db-conventions.md` |
| Security-sensitive paths | §B11, §C5.8, §C5.9 | `.claude/rules/security.md` |
| Naming | §C1 | `.claude/rules/python-style.md`, `frontend-style.md` |
| Tests | §C8 | `.claude/rules/testing.md` |
| Done | §C11 | `.claude/references/definition-of-done.md` |

## Current focus

**Gate G0 -> Phase 1 (standards and platform core)**, milestones M1.1 to M1.6 (plan §D1, §D2). The task list and status live in `docs/tracker/roadmap-tracker.md` (created in M1.1); until it exists, the lead engineer names the task. Do not build asset (Phase 2) or maintenance (Phase 3) features ahead of their gates.

## Repository layout (§B4.3)

```
backend/app/        main.py · core/ · providers/{auth,secrets,telemetry,events}/ · channels/
                    engines/{workflow,automation}/ · modules/{organization,assets,maintenance,notifications,audit}/ · api/v1/
backend/workers/    outbox_dispatcher · schedule_evaluator · sla_sweeper · notification_sender · job_runner
backend/migrations/ Alembic, raw SQL
backend/tests/      unit/ integration/ isolation/ scope/ contract/ authz_matrix/ e2e_api/
frontend/src/       app/ · features/ · components/ui/ · lib/{api,auth,config,permissions,i18n} · styles/tokens.css
config/             assetflow.yaml · domains/*.yaml · templates/
deploy/             compose.minimal.yml · compose.full.yml · bootstrap/ · nginx/ · grafana/
docs/               decisions/ specs/ guides/ operations/ security/ reviews/ reference/ tracker/
scripts/            bootstrap.* · check-*.sh/py · new-channel.py · demo-data.py
.claude/            loop config, hooks, rules, context, agents, commands (see .claude/README.md)
```

## Non-negotiables

1. **Tenancy**: every tenant table has `organization_id NOT NULL`, RLS `ENABLE` + `FORCE`, four fail-closed policies, an `organization_id`-first index; views are `security_invoker`. Every migration ships with isolation/scope tests.
2. **Scopes**: permission and scope checked on the loaded record (`ctx.scope.require`); every list query takes a `ScopeFilter`; denied reads return 404.
3. **One transaction per write**: change + `audit_events` + `outbox` row together. No external calls inside a request.
4. **Secrets**: every server-side credential lives in **OpenBao** in production; config holds only `secret://` references; the browser holds no credentials. Never write a secret anywhere else.
5. **No PII in logs**, traces or metrics; pseudonymous member ids only.
6. **Config-first**: industry- or organization-specific behaviour goes in `config/domains/*.yaml`, never in code. Neutral vocabulary only (§C1.2).
7. **CLA**, not DCO: no `Signed-off-by`. Conventional Commits. Every file has the SPDX header (`SPDX-FileCopyrightText: <year> TinyPhi`, `SPDX-License-Identifier: AGPL-3.0-only`).
8. **Security paths** (§C5.8) need the security-reviewer verdict and the second reviewer's approval (CODEOWNERS).
9. The agent never merges, never pushes to `main`, never approves its own plan or ship.

## Commands

| Command | Purpose |
| --- | --- |
| `make deps` | Install backend (uv) and frontend (npm) dependencies and the pre-commit hooks |
| `make bootstrap` | Identity setup (same as `scripts/bootstrap.sh` / `setup.bat`): `.env.local` secrets, Zitadel, idempotent Zitadel bootstrap ([guide](docs/guides/setup-zitadel.md)) |
| `make up-identity` / `make down-identity` | Start / stop the local development Zitadel |
| `make zitadel-apply [DRY_RUN=1]` / `make openbao-apply` | Re-apply the Zitadel bootstrap / the OpenBao configuration ([guide](docs/guides/setup-openbao.md)) |
| `make test-scripts` | Tests of the setup scripts |
| `make up-minimal` / `make up-full` / `make down` | Start/stop a profile |
| `make fmt` / `make lint` / `make typecheck` | ruff + prettier / linters + import-linter + domain terms + migration lint / mypy + tsc |
| `make test` / `make test-backend ARGS="..."` / `make test-frontend` | Tests |
| `make test-isolation` | Organization isolation and scope-leakage suites |
| `make test-contract` / `make test-e2e-api` | Provider/channel contracts / API E2E flows |
| `make migration name=<snake>` / `make migrate` | New migration from the template / apply |
| `make config-validate` / `make docs-check` | Validate `config/**/*.yaml` / docs links and generated references |
| `make verify` | Everything CI's quality and test jobs run |
| `python .claude/hooks/af.py status` | Branch, plan and open gates |
| `python .claude/hooks/af.py next-task` | Draft the next tracker task as a plan |
| `python .claude/hooks/af.py verify` / `ship` / `done` | Record verify, ship-ready, done (see `.claude/README.md`) |

Human keywords: `approve-plan`, `approve-ship`.

## How rules load

- `.claude/rules/agent-behaviour.md` and `.claude/rules/git-conventions.md` load in every session.
- The other rule files have `paths:` frontmatter and load when matching files are read or edited: `python-style.md` (`backend/**/*.py`), `frontend-style.md` (`frontend/**`), `db-conventions.md` (migrations, repositories, isolation/scope tests, `*.sql`), `security.md` (§C5.8 paths), `testing.md` (tests and `loadtest/`).
- Context files in `.claude/context/` are not auto-loaded: read the one for your area first.

## When stuck

Stop and add an entry to `docs/tracker/BLOCKERS.md` (task id, blocker, evidence, what you tried, the decision needed), mark the tracker row `⛔`, and end the unit. Triggers: a contract change not in the plan, an ambiguous criterion, the same test failing after 2 attempts, a security `block`, an off-limits path, or behaviour that should be config but the engines cannot express it.
