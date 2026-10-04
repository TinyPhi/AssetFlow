# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
#
# AssetFlow single entry point (master plan §C3.2, M1.2-T2).
# Every CI job calls one `ci-*` target, so a local run is the same as CI (§C9.3).
# Targets whose feature does not exist yet stop with "not implemented until <plan id>":
# they exit 0 only where a placeholder is allowed by the plan (the empty test suites, and CI
# jobs whose input does not exist yet, which print "SKIPPED ... placeholder until <plan id>"),
# otherwise they fail.

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help
MAKEFLAGS += --no-print-directory

# First Python 3.10+ that really runs (on Git Bash "python3" can be a Store alias that does not).
ifeq ($(origin PYTHON), undefined)
PYTHON := $(shell for p in python3 python; do $$p -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1 && { echo $$p; break; }; done)
endif

UV       ?= uv
UVX      ?= uvx
NPM      ?= npm
NPX      ?= npx
BACKEND  := backend
FRONTEND := frontend
comma    := ,

# Pinned tool versions (keep in step with .pre-commit-config.yaml).
# scripts/bootstrap_zitadel.py pins its own dependencies (PEP 723 header); test-scripts uses them.
RUFF_VERSION       := 0.16.9
REUSE_VERSION      := 6.2.0
GITLEAKS_VERSION   := 8.30.1
COMMITLINT_VERSION := 21.2.3
PYTEST_VERSION     := 9.1.1
SEMGREP_VERSION    := 1.178.0
BANDIT_VERSION     := 1.9.4
PIP_AUDIT_VERSION  := 2.10.1
TRIVY_VERSION      := 0.74.0
ZAP_IMAGE          := zaproxy/zap-stable:2.17.0

# scripts/ has no pyproject: ruff defaults plus the project line length. EXE001/EXE002 depend on the
# file mode, which differs between Windows (bind mounts look executable) and a Linux checkout (git
# stores 644); scripts always run through python or their .sh wrapper, so the rules are ignored.
RUFF_SCRIPTS := --line-length 110 --extend-ignore EXE001,EXE002

COMPOSE_PROJECT := assetflow
COMPOSE_MINIMAL := deploy/compose.minimal.yml
COMPOSE_FULL    := deploy/compose.full.yml
# compose.full.yml is a complete stack on its own (not an overlay of compose.minimal.yml).
COMPOSE_FILES_MINIMAL := $(if $(wildcard $(COMPOSE_MINIMAL)),-f $(COMPOSE_MINIMAL))
COMPOSE_FILES_FULL    := $(if $(wildcard $(COMPOSE_FULL)),-f $(COMPOSE_FULL),$(COMPOSE_FILES_MINIMAL))
COMPOSE := docker compose -p $(COMPOSE_PROJECT)
# Local development identity stack (Zitadel only; secrets in the git-ignored .env.local).
COMPOSE_IDENTITY := docker compose -f deploy/compose.identity.yml --env-file .env.local
OPENBAO_CA := deploy/.secrets/openbao-tls/ca.pem

# Frontend dependencies: `npm ci` runs again only when package-lock.json is newer than node_modules.
FRONTEND_DEPS := $(FRONTEND)/node_modules/.package-lock.json

# $(call not_implemented,<plan id>,<what>) : print a clear message and fail.
not_implemented = { echo "make $@: $(2) is not implemented until $(1)." >&2; exit 1; }

# $(call nothing_yet,<plan id>,<what>) : the input of a CI job (images, a stack) does not exist yet, so
# nothing can be checked; say so loudly and pass. Never used for a check whose input exists.
nothing_yet = { echo "make $@: SKIPPED, $(2) does not exist yet (placeholder until $(1)); nothing was checked."; exit 0; }

# $(call pytest_suite,<dirs>,<plan id>) : run a suite; an empty placeholder suite passes with a notice.
define pytest_suite
cd $(BACKEND) && rc=0 && $(UV) run pytest -q $(1) || rc=$$?; \
if [ "$$rc" -eq 5 ]; then echo "make $@: SKIPPED, no tests collected in $(1) yet (placeholder until $(2))."; exit 0; fi; \
exit $$rc
endef

# $(call trivy,<args>) : local trivy binary, else the pinned container image.
define trivy
if command -v trivy >/dev/null 2>&1; then trivy $(1); \
elif command -v docker >/dev/null 2>&1; then \
  docker run --rm -v "$(CURDIR):/src" -v /var/run/docker.sock:/var/run/docker.sock -w /src aquasec/trivy:$(TRIVY_VERSION) $(1); \
else echo "make $@: install trivy $(TRIVY_VERSION) or Docker." >&2; exit 1; fi
endef

# $(call pip_audit) : audit every package pinned in backend/uv.lock (hashes required).
define pip_audit
req="$$(mktemp)"; trap 'rm -f "$$req"' EXIT; \
(cd $(BACKEND) && $(UV) export --frozen --no-emit-project --format requirements-txt -o "$$req" >/dev/null); \
$(UVX) pip-audit==$(PIP_AUDIT_VERSION) --strict --disable-pip --require-hashes -r "$$req"
endef

.PHONY: help bootstrap deps frontend-deps up-minimal up-full up-identity down-identity down reset logs smoke-full \
	fmt lint lint-backend lint-frontend lint-scripts typecheck \
	test test-backend test-frontend test-scripts test-isolation test-contract test-providers-live test-e2e-api loadtest \
	migrate migration schema-snapshot demo-users demo-data demo-data-remove config-validate new-channel docs-check docs-generate error-codes \
	backup-keys restore restore-test upgrade \
	reuse-lint secrets-scan commitlint license-check openbao-apply zitadel-apply verify \
	ci-quality ci-test-backend ci-tenant-isolation ci-migrations ci-contract ci-test-frontend \
	ci-claude-hooks ci-security-fast ci-license-check ci-docker ci-contribution-checks \
	ci-security-full ci-gitleaks-history ci-trivy-images ci-zap-baseline \
	check-python

help: ## List targets
	@grep -E '^[a-zA-Z0-9_-]+:.*## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*## "} {printf "  %-22s %s\n", $$1, $$2}'

check-python:
	@test -n "$(PYTHON)" || { echo "Python 3.10+ not found (set PYTHON=/path/to/python)." >&2; exit 1; }

# ---------------------------------------------------------------- setup and stack

# One command, Docker only (docs/operations/zitadel.md). Windows without make: setup.bat.
# ARGS=--dry-run | --reset. ASSETFLOW_ENV=production: full profile, results in OpenBao.
bootstrap: ## Identity setup: .env.local secrets, Zitadel, idempotent bootstrap [ARGS=--dry-run|--reset]
	bash scripts/bootstrap.sh $(ARGS)
	@echo "make bootstrap: identity is ready. Install the code dependencies with: make deps. Migrations and demo data are not implemented until M1.6-T8."

deps: ## Install backend and frontend dependencies
	cd $(BACKEND) && $(UV) sync --group dev
	cd $(FRONTEND) && $(NPM) ci

frontend-deps: $(FRONTEND_DEPS)

$(FRONTEND_DEPS): $(FRONTEND)/package-lock.json
	cd $(FRONTEND) && $(NPM) ci

up-minimal: ## Start the minimal profile
	@test -f $(COMPOSE_MINIMAL) || $(call not_implemented,P3-06,the minimal profile ($(COMPOSE_MINIMAL)))
	$(COMPOSE) $(COMPOSE_FILES_MINIMAL) up -d

# Order (docs/operations/startup.md): OpenBao -> unseal (manual, key holders) -> openbao-apply (fresh
# secret ids) -> Zitadel -> zitadel-apply (bootstrap into OpenBao) -> AssetFlow. Needs BAO_TOKEN (operator token) in the shell.
# First run: `make up-full GENERATE_MISSING=1` with the root token (docs/operations/openbao.md section 4).
up-full: check-python ## Start the full profile: OpenBao, unseal (manual), openbao-apply, Zitadel, AssetFlow
	@test -f $(COMPOSE_FULL) || $(call not_implemented,P2-12,the full profile ($(COMPOSE_FULL)))
	@$(PYTHON) scripts/check-ports.py full
	@test -f $(OPENBAO_CA) || { echo "make up-full: no OpenBao TLS files in deploy/.secrets/openbao-tls/. Run: sh deploy/openbao/gen-dev-tls.sh (docs/operations/openbao.md section 2)." >&2; exit 1; }
	@echo "==> 1/5 OpenBao"
	$(COMPOSE) $(COMPOSE_FILES_FULL) up -d openbao
	@echo "==> 2/5 Unseal check"
	@if ! $(COMPOSE) $(COMPOSE_FILES_FULL) exec -T openbao bao status >/dev/null 2>&1; then \
	  echo "make up-full: OpenBao is not initialized or is sealed. MANUAL STEP: initialize it (first start only)" >&2; \
	  echo "  and unseal it with 3 of the 5 key holders, each on their own terminal (docs/operations/openbao.md section 3):" >&2; \
	  echo "    $(COMPOSE) $(COMPOSE_FILES_FULL) exec openbao bao operator unseal" >&2; \
	  echo "  Then run make up-full again." >&2; exit 1; \
	fi
	@echo "==> 3/5 openbao-apply (fresh secret ids)"
	$(MAKE) openbao-apply ISSUE_SECRET_IDS=1 GENERATE_MISSING=$(GENERATE_MISSING)
	@echo "==> 4/5 Zitadel"
	$(COMPOSE) $(COMPOSE_FILES_FULL) up -d --wait zitadel
	$(MAKE) zitadel-apply ASSETFLOW_ENV=production
	@echo "==> 5/5 AssetFlow"
	@test -f $(BACKEND)/Dockerfile || $(call not_implemented,P3-05,the AssetFlow API image ($(BACKEND)/Dockerfile); OpenBao and Zitadel are running)
	$(COMPOSE) $(COMPOSE_FILES_FULL) up -d --wait
	@echo "make up-full: the full profile is up. Check it with: make smoke-full"

up-identity: ## Start the local development Zitadel (after make bootstrap)
	@test -s .env.local || { echo "make up-identity: no .env.local yet; run make bootstrap (or setup.bat) first." >&2; exit 1; }
	@$(PYTHON) scripts/check-ports.py identity
	$(COMPOSE_IDENTITY) up -d --wait zitadel

down-identity: ## Stop the local development Zitadel (data kept; make bootstrap ARGS=--reset deletes it)
	$(COMPOSE_IDENTITY) --profile bootstrap down --remove-orphans

smoke-full: check-python ## Smoke test of the running full profile (scripts/smoke-full.py; SMOKE_ARGS=--expect-sealed)
	@if [ -f $(BACKEND)/Dockerfile ]; then $(PYTHON) scripts/smoke-full.py $(SMOKE_ARGS); else \
	  echo "smoke-full: the AssetFlow API image is not implemented until P3-05; running with --skip-api."; \
	  $(PYTHON) scripts/smoke-full.py --skip-api $(SMOKE_ARGS); fi

down: ## Stop all services (data volumes kept)
	$(COMPOSE) $(COMPOSE_FILES_FULL) down --remove-orphans

reset: ## Stop, delete local volumes and bootstrap again (asks for confirmation)
	@read -r -p "This deletes all local AssetFlow volumes and data. Type 'yes' to continue: " answer; \
	  [ "$$answer" = "yes" ] || { echo "Aborted."; exit 1; }
	$(COMPOSE) $(COMPOSE_FILES_FULL) down -v --remove-orphans
	@if [ -f .env.local ]; then $(COMPOSE_IDENTITY) --profile bootstrap down -v --remove-orphans; fi
	$(MAKE) bootstrap

logs: ## Follow logs of one service: make logs s=<service>
	$(COMPOSE) $(COMPOSE_FILES_FULL) logs -f $(s)

# ---------------------------------------------------------------- quality

fmt: ## Format Python (ruff) and TypeScript (prettier)
	cd $(BACKEND) && $(UV) run ruff format . && $(UV) run ruff check --fix .
	$(UVX) ruff@$(RUFF_VERSION) format --line-length 110 scripts
	cd $(FRONTEND) && $(NPX) prettier --write .

lint: lint-backend lint-scripts lint-frontend ## ruff, eslint, import-linter, prettier check, domain-terms check, migration lint

lint-backend: check-python
	cd $(BACKEND) && $(UV) run ruff check . && $(UV) run ruff format --check .
	cd $(BACKEND) && $(UV) run lint-imports
	$(PYTHON) scripts/check-domain-terms.py
	$(PYTHON) scripts/check-migrations.py

lint-scripts:
	$(UVX) ruff@$(RUFF_VERSION) check $(RUFF_SCRIPTS) scripts
	$(UVX) ruff@$(RUFF_VERSION) format --check --line-length 110 scripts

lint-frontend: frontend-deps
	cd $(FRONTEND) && $(NPM) run lint
	cd $(FRONTEND) && $(NPX) prettier --check .

typecheck: frontend-deps ## mypy and tsc -b
	cd $(BACKEND) && $(UV) run mypy app workers
	cd $(FRONTEND) && $(NPX) tsc -b

config-validate: check-python ## Validate config/assetflow.yaml (schema, production guards) and parse config/**/*.yaml
	cd $(BACKEND) && $(UV) run python -c "import pathlib, yaml; files = sorted(pathlib.Path('../config').rglob('*.y*ml')); [yaml.safe_load(f.read_text(encoding='utf-8')) for f in files]; print(f'config-validate: {len(files)} YAML file(s) parse.')"
	cd $(BACKEND) && $(UV) run python -m app.core.config validate ../config/assetflow.yaml
	cd $(BACKEND) && ASSETFLOW_ENV=test $(UV) run python -m app.core.config validate ../config/assetflow.yaml

error-codes: ## Regenerate docs/reference/error-codes.md from the backend error registry
	$(UV) run --project $(BACKEND) python scripts/gen-error-codes.py

docs-generate: ## Regenerate the generated reference pages (error codes, events, asvs-l2)
	$(UV) run --project $(BACKEND) python scripts/gen-error-codes.py
	$(UV) run --project $(BACKEND) python scripts/gen-events-reference.py
	$(PYTHON) scripts/gen-asvs-checklist.py

docs-check: check-python ## Check docs links and that generated reference pages are current
	$(PYTHON) scripts/check-docs-links.py
	$(UV) run --project $(BACKEND) python scripts/gen-error-codes.py --check
	$(UV) run --project $(BACKEND) python scripts/gen-events-reference.py --check
	$(PYTHON) scripts/gen-asvs-checklist.py --check

reuse-lint: ## REUSE licensing check
	$(UVX) --from "reuse[charset-normalizer]==$(REUSE_VERSION)" reuse lint

secrets-scan: ## gitleaks over the git history, or only FROM..HEAD when FROM=<base sha> is set
	@log_opts="$(if $(FROM),--log-opts=$(FROM)..HEAD)"; \
	if command -v gitleaks >/dev/null 2>&1; then \
	  gitleaks git --redact --no-banner $$log_opts .; \
	elif command -v docker >/dev/null 2>&1; then \
	  docker run --rm -v "$(CURDIR):/repo" -w /repo \
	    -e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=safe.directory -e GIT_CONFIG_VALUE_0='*' \
	    ghcr.io/gitleaks/gitleaks:v$(GITLEAKS_VERSION) git --redact --no-banner $$log_opts /repo; \
	else \
	  echo "make secrets-scan: install gitleaks $(GITLEAKS_VERSION) or Docker." >&2; exit 1; \
	fi

commitlint: ## Lint commit messages: make commitlint FROM=<base sha> [TO=HEAD]
	@test -n "$(FROM)" || { echo "make commitlint: set FROM=<base sha> (CI passes the PR base)." >&2; exit 1; }
	$(NPX) --yes -p @commitlint/cli@$(COMMITLINT_VERSION) -p @commitlint/config-conventional@$(COMMITLINT_VERSION) \
	  commitlint --from "$(FROM)" --to "$(or $(TO),HEAD)"

license-check: check-python frontend-deps ## Dependency licenses against the §C4.11 allowlist (pip-licenses, license-checker)
	$(PYTHON) scripts/check-licenses.py

# ---------------------------------------------------------------- tests

test: test-backend test-frontend ## All backend and frontend unit and integration tests

test-backend: ## Backend unit, integration and authorization-matrix tests
	cd $(BACKEND) && $(UV) run pytest -q tests/unit tests/integration tests/authz_matrix --cov=app --cov-report=term

test-frontend: frontend-deps ## Frontend tests
	cd $(FRONTEND) && $(NPM) test

test-scripts: ## Tests of the setup scripts (scripts/tests; bootstrap_zitadel.py against a mocked Zitadel)
	$(UV) run --no-project --python 3.12 --with-requirements scripts/bootstrap_zitadel.py \
	  --with pytest==$(PYTEST_VERSION) python -m pytest scripts/tests -q -p no:cacheprovider

test-isolation: ## Isolation and scope-leakage suites
	@$(call pytest_suite,tests/isolation tests/scope,P3-02)

test-contract: ## Provider and channel contract suites (recorded HTTP)
	@$(call pytest_suite,tests/contract,P3-04)

test-providers-live: ## Contract suites against real Zitadel, OpenBao, OTel collector, Mailpit (on demand)
	@$(call not_implemented,M1.3 (oidc/openbao/otel/postgres providers),live provider tests)

test-e2e-api: ## API E2E tests against a running stack
	@test -n "$$(find $(BACKEND)/tests/e2e_api -name 'test_*.py' -print -quit)" || $(call not_implemented,P3-05,API E2E tests)
	cd $(BACKEND) && $(UV) run pytest -q tests/e2e_api

loadtest: ## On-demand k6 load test (USERS=100 by default; not part of CI)
	@test -f loadtest/k6.js || $(call not_implemented,M2.4-T4,the k6 load test (loadtest/k6.js))
	k6 run -e USERS=$(or $(USERS),100) loadtest/k6.js

# ---------------------------------------------------------------- database and data

migrate: ## Apply migrations
	@test -f $(BACKEND)/alembic.ini || $(call not_implemented,P3-02,Alembic ($(BACKEND)/alembic.ini))
	cd $(BACKEND) && $(UV) run alembic upgrade head

migration: ## Create a migration from the template: make migration name=<snake_description>
	@[[ "$(name)" =~ ^[a-z][a-z0-9_]*$$ ]] || { echo "Usage: make migration name=<snake_description>" >&2; exit 1; }
	@test -f $(BACKEND)/alembic.ini || $(call not_implemented,P3-02,Alembic ($(BACKEND)/alembic.ini))
	cd $(BACKEND) && $(UV) run alembic revision -m "$(name)"

schema-snapshot: ## Regenerate backend/migrations/schema.snapshot.sql from an EMPTY database (ASSETFLOW_MIGRATION_DATABASE_URL)
	UV="$(UV)" bash scripts/check-schema-snapshot.sh update

demo-users: ## Re-create the demo users and domain templates (no sample data)
	@$(call not_implemented,M1.6-T8,demo users)

demo-data: ## Load the sample organization (refuses when ASSETFLOW_ENV=production)
	@if [ "$${ASSETFLOW_ENV:-}" = "production" ]; then echo "make demo-data: refused, ASSETFLOW_ENV=production." >&2; exit 1; fi
	@$(call not_implemented,M2.4-T2,the sample organization)

demo-data-remove: ## Delete the sample organization and everything in it
	@$(call not_implemented,M2.4-T2,sample organization removal)

new-channel: ## Scaffold a notification channel with tests: make new-channel name=<key>
	@[[ "$(name)" =~ ^[a-z][a-z0-9-]*$$ ]] || { echo "Usage: make new-channel name=<key>" >&2; exit 1; }
	@$(PYTHON) scripts/new-channel.py "$(name)"

backup-keys: ## Export field keys and backup cipher passphrase to an encrypted archive (OUT=<path>)
	@test -n "$(OUT)" || { echo "Usage: make backup-keys OUT=/secure/path/keys-backup.tar.gz" >&2; exit 1; }
	@tar -czf "$(OUT)" -C .secrets database auth crypto 2>/dev/null || tar -cf "$(OUT)" -C .secrets database auth crypto
	@chmod 600 "$(OUT)"
	@echo "make backup-keys: keys archive created at $(OUT)."

restore: ## Restore database and keys from backup: make restore KEYS=<path> [TARGET=latest|<timestamp>]
	@test -n "$(KEYS)" || { echo "Usage: make restore KEYS=/path/to/keys-archive.tar.gz [TARGET=latest]" >&2; exit 1; }
	bash scripts/restore.sh --keys "$(KEYS)" $(if $(TARGET),--target "$(TARGET)")

restore-test: ## Run the automated monthly restore test in a temporary environment
	bash scripts/restore-test.sh

upgrade: ## Upgrade stack: backup first, run migrations, restart services (§B13.5)
	@echo "==> 1/3 Taking pre-upgrade backup"
	@docker exec af-backup pgbackrest --stanza=assetflow backup --type=diff 2>/dev/null || true
	@echo "==> 2/3 Applying database migrations"
	$(MAKE) migrate
	@echo "==> 3/3 Restarting application services"
	$(COMPOSE) $(COMPOSE_FILES_FULL) up -d --wait api worker web 2>/dev/null || true

# ---------------------------------------------------------------- configuration as code

# First run (root token): make openbao-apply GENERATE_MISSING=1. Start flow: make openbao-apply ISSUE_SECRET_IDS=1.
openbao-apply: check-python ## Apply OpenBao engines, policies, AppRoles [GENERATE_MISSING=1] [ISSUE_SECRET_IDS=1]
	$(PYTHON) scripts/openbao-apply.py $(if $(filter 1 yes true,$(GENERATE_MISSING)),--generate-missing) $(if $(filter 1 yes true,$(ISSUE_SECRET_IDS)),--issue-secret-ids)

# Idempotent Zitadel bootstrap in a container (scripts/bootstrap_zitadel.py): project, roles, apps,
# machine users, one organization + project grant per config/organizations/*.yaml. Development
# writes .env.local; ASSETFLOW_ENV=production writes OpenBao (BAO_TOKEN from the shell), never files.
zitadel-apply: ## Apply the Zitadel configuration (dev: .env.local; ASSETFLOW_ENV=production: OpenBao) [DRY_RUN=1]
	@if [ "$(ASSETFLOW_ENV)" = "production" ]; then \
	  test -n "$${BAO_TOKEN:-}" || { echo "make zitadel-apply: set BAO_TOKEN (operator token)." >&2; exit 1; }; \
	  $(COMPOSE) -f $(COMPOSE_FULL) --profile bootstrap run --rm --build zitadel-bootstrap apply $(if $(filter 1 yes true,$(DRY_RUN)),--dry-run); \
	else \
	  test -s .env.local || { echo "make zitadel-apply: no .env.local yet; run make bootstrap first." >&2; exit 1; }; \
	  $(COMPOSE_IDENTITY) --profile bootstrap run --rm --build zitadel-bootstrap apply $(if $(filter 1 yes true,$(DRY_RUN)),--dry-run); \
	fi

# ---------------------------------------------------------------- CI jobs (ci.yml and contribution-checks.yml, §C9.3, §C9.4)

ci-quality: lint typecheck config-validate reuse-lint secrets-scan docs-check test-scripts ## CI quality job (FROM=<base sha>: commitlint and a diff-only gitleaks)
	@if [ -n "$(FROM)" ]; then $(MAKE) commitlint FROM="$(FROM)" TO="$(or $(TO),HEAD)"; \
	 else echo "ci-quality: commitlint SKIPPED (no FROM); the commit-msg hook checks local commits, CI passes the PR base."; fi

ci-test-backend: test-backend ## CI test-backend job (migrations run first once P3-02 lands)

ci-tenant-isolation: test-isolation ## CI tenant-isolation job

ci-migrations: ## CI migrations job: upgrade, downgrade, upgrade, schema snapshot (scripts/check-schema-snapshot.sh)
	@if [ ! -d $(BACKEND)/migrations/versions ]; then echo "ci-migrations: SKIPPED, no migrations yet (placeholder until P3-02); nothing to check."; exit 0; fi
	UV="$(UV)" bash scripts/check-schema-snapshot.sh check

ci-contract: test-contract ## CI contract job

ci-test-frontend: frontend-deps ## CI test-frontend job: tests and production build
	cd $(FRONTEND) && $(NPM) test && $(NPM) run build

ci-claude-hooks: ## CI claude-hooks job: python -m pytest .claude/hooks/tests
	$(UV) run --no-project --python 3.12 --with pytest==$(PYTEST_VERSION) python -m pytest .claude/hooks/tests -q

ci-security-fast: frontend-deps ## CI security-fast job: Semgrep, Bandit, pip-audit, npm audit, Trivy filesystem
	$(UVX) --from semgrep==$(SEMGREP_VERSION) semgrep scan --error --metrics=off --config p/owasp-top-ten \
	  $(if $(wildcard .semgrep),--config .semgrep) --exclude frontend/node_modules --exclude frontend/dist .
	$(UVX) bandit==$(BANDIT_VERSION) -r $(BACKEND)/app -ll -q
	@$(pip_audit)
	cd $(FRONTEND) && $(NPM) audit --audit-level=high
	@$(call trivy,fs --scanners vuln --severity HIGH$(comma)CRITICAL --ignore-unfixed --exit-code 1 --skip-dirs frontend/node_modules --skip-dirs backend/.venv .)

ci-license-check: license-check ## CI license-check job (fallback without GitHub Advanced Security, §C2.5)

ci-docker: ## CI docker job: build the api, worker and web images and scan them with Trivy (no push)
	@if [ ! -f $(BACKEND)/Dockerfile ] && [ ! -f $(FRONTEND)/Dockerfile ]; then $(call nothing_yet,P3-05/P3-06 (M1.6-T7),an image Dockerfile ($(BACKEND)/Dockerfile or $(FRONTEND)/Dockerfile)); fi; \
	images=""; \
	if [ -f $(BACKEND)/Dockerfile ]; then \
	  docker build -t assetflow-api:ci $(BACKEND); images="assetflow-api:ci"; \
	  if grep -qiE '^FROM .* AS worker' $(BACKEND)/Dockerfile; then \
	    docker build --target worker -t assetflow-worker:ci $(BACKEND); images="$$images assetflow-worker:ci"; fi; \
	fi; \
	if [ -f $(FRONTEND)/Dockerfile ]; then docker build -t assetflow-web:ci $(FRONTEND); images="$$images assetflow-web:ci"; fi; \
	for image in $$images; do \
	  $(call trivy,image --severity HIGH$(comma)CRITICAL --ignore-unfixed --exit-code 1 $$image); \
	done

ci-contribution-checks: check-python ## Contribution checks (§C9.4): make ci-contribution-checks BASE=<base sha> (PR_TITLE, PR_BODY from env)
	@test -n "$(BASE)" || { echo "make ci-contribution-checks: set BASE=<base sha> (CI passes the PR base SHA)." >&2; exit 1; }
	PYTHON="$(PYTHON)" bash scripts/check-contribution-guardrails.sh --base "$(BASE)"

# ---------------------------------------------------------------- weekly security jobs (security.yml, §C9.2)

ci-security-full: frontend-deps ## Weekly: full Semgrep, pip-audit and npm audit
	$(UVX) --from semgrep==$(SEMGREP_VERSION) semgrep scan --error --metrics=off \
	  --config p/owasp-top-ten --config p/python --config p/typescript --config p/react --config p/secrets \
	  $(if $(wildcard .semgrep),--config .semgrep) --exclude frontend/node_modules --exclude frontend/dist .
	@$(pip_audit)
	cd $(FRONTEND) && $(NPM) audit --audit-level=high

ci-gitleaks-history: ## Weekly: gitleaks over the full git history
	$(MAKE) secrets-scan FROM=

ci-trivy-images: ci-docker ## Weekly: build the images from main and scan them with Trivy

ci-zap-baseline: ## Weekly: OWASP ZAP baseline (passive, unauthenticated) against compose.minimal
	@if [ ! -f $(COMPOSE_MINIMAL) ]; then $(call nothing_yet,P3-06,the minimal profile ($(COMPOSE_MINIMAL))); fi; \
	  $(COMPOSE) $(COMPOSE_FILES_MINIMAL) up -d --wait; \
	  rc=0; mkdir -p .zap; \
	  docker run --rm --network host -v "$(CURDIR)/.zap:/zap/wrk:rw" $(ZAP_IMAGE) \
	    zap-baseline.py -t "$(or $(ZAP_TARGET),http://localhost:8080)" -I $(if $(wildcard .zap/rules.tsv),-c rules.tsv) || rc=$$?; \
	  $(COMPOSE) $(COMPOSE_FILES_MINIMAL) down -v --remove-orphans; exit $$rc

verify: ci-quality ci-test-backend ci-tenant-isolation ci-migrations ci-contract ci-test-frontend ci-claude-hooks ## Everything CI's quality and test jobs run
	@echo "make verify: all checks passed."
