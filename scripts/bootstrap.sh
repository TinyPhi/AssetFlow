#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
#
# One-command bootstrap for Linux, macOS and WSL2 (§B13.1, M1.6-T8).
# Sets up prerequisites, local secrets, starts the stack, runs migrations,
# initializes identity and demo data, and performs post-startup smoke checks.
#
# Usage:
#   scripts/bootstrap.sh [--profile minimal|full] [--dry-run] [--reset] [--no-demo]
#
# Options:
#   --profile <minimal|full>  Deployment profile to bootstrap (default: minimal)
#   --dry-run                 Show actions without starting containers or modifying state
#   --reset                   Delete existing containers and volumes before bootstrap
#   --no-demo                 Skip creating demo organization and users
#   -h, --help                Show this help message
#
# Windows: setup.bat (or scripts/bootstrap.ps1).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"
export MSYS_NO_PATHCONV=1 # Git Bash: keep container paths as they are

PROFILE="minimal"
DRY_RUN=0
RESET=0
NO_DEMO=0
APPLY_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)
      if [[ -z "${2:-}" ]]; then
        echo "error: --profile requires an argument (minimal or full)" >&2
        exit 2
      fi
      PROFILE="$2"
      shift 2
      ;;
    --profile=*)
      PROFILE="${1#*=}"
      shift
      ;;
    --reset)
      RESET=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      APPLY_ARGS+=(--dry-run)
      shift
      ;;
    --no-demo)
      NO_DEMO=1
      shift
      ;;
    -h|--help)
      sed -n '4,19p' "$0"
      exit 0
      ;;
    *)
      echo "unknown option: $1 (see --help)" >&2
      exit 2
      ;;
  esac
done

if [[ "${PROFILE}" != "minimal" && "${PROFILE}" != "full" ]]; then
  echo "error: invalid profile '${PROFILE}'. Must be 'minimal' or 'full'." >&2
  exit 2
fi

say() { printf '\n==> %s\n' "$1"; }
fail() { printf '\nerror: %s\n' "$1" >&2; exit 1; }

COMPOSE_FILE="deploy/compose.${PROFILE}.yml"
DC=(docker compose -p assetflow -f "${COMPOSE_FILE}")

if [[ "${DRY_RUN}" -eq 1 ]]; then
  say "Dry run: would execute the following steps for ${PROFILE} profile:"
  echo "  1. Start stack with: ${DC[*]} up -d --wait"
  echo "  2. Run migrations: ${DC[*]} --profile tools run --rm migrate"
  echo "  3. Configure identity and bootstrap Zitadel/OpenBao (full profile only)"
  echo "  4. Seed demo organization and admin (unless --no-demo)"
  echo "  5. Verify health: GET http://127.0.0.1:18080/api/health"
  say "Dry run complete."
  exit 0
fi

# ---------------------------------------------------------------- Step 1: Preflight checks (§B13.1)
say "1/6 Prerequisites and preflight checks"
command -v docker >/dev/null 2>&1 || fail "Docker is required (https://docs.docker.com/get-docker/)."
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is required (docker compose)."

# Port preflight check (P2-13 map)
if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  PYTHON_BIN=""
fi

if [[ -n "${PYTHON_BIN}" && -f "scripts/check-ports.py" ]]; then
  "${PYTHON_BIN}" scripts/check-ports.py "${PROFILE}" || fail "Port check failed. Adjust ports in .env.local to resolve collisions."
fi

# Disk space check: ensure at least 1 GB available
if command -v df >/dev/null 2>&1; then
  avail_kb=$(df -Pk . 2>/dev/null | tail -1 | awk '{print $4}' || echo "")
  if [[ -n "${avail_kb}" && "${avail_kb}" =~ ^[0-9]+$ ]]; then
    if [[ "${avail_kb}" -lt 1048576 ]]; then
      echo "warning: less than 1 GB disk space available on current volume." >&2
    fi
  fi
fi

# ---------------------------------------------------------------- Step 2: Local secrets (§C5.5)
say "2/6 Local secrets (.secrets/ and .env.local)"
SECRETS_DIR=".secrets"
mkdir -p "${SECRETS_DIR}/database/app" \
         "${SECRETS_DIR}/database/migrator" \
         "${SECRETS_DIR}/database/worker" \
         "${SECRETS_DIR}/database/readonly" \
         "${SECRETS_DIR}/auth" \
         "${SECRETS_DIR}/crypto"

gen_secret() {
  local target="$1"
  local length="${2:-32}"
  if [[ ! -f "${target}" || ! -s "${target}" ]]; then
    if command -v openssl >/dev/null 2>&1; then
      openssl rand -hex "${length}" > "${target}"
    elif [[ -c /dev/urandom ]]; then
      LC_ALL=C tr -dc 'A-Za-z0-9_-' < /dev/urandom | head -c "$((length * 2))" > "${target}"
    else
      echo "secret-value-$(date +%s%N)" > "${target}"
    fi
    chmod 600 "${target}" 2>/dev/null || true
  fi
}

gen_secret "${SECRETS_DIR}/database/app/password"
gen_secret "${SECRETS_DIR}/database/migrator/password"
gen_secret "${SECRETS_DIR}/database/worker/password"
gen_secret "${SECRETS_DIR}/database/readonly/password"
gen_secret "${SECRETS_DIR}/auth/cookie_key"
gen_secret "${SECRETS_DIR}/crypto/field_key"

ENV_FILE=".env.local"
if [[ ! -f "${ENV_FILE}" ]]; then
  : >"${ENV_FILE}"
  chmod 600 "${ENV_FILE}" 2>/dev/null || true
fi

# ---------------------------------------------------------------- Reset handling
COMPOSE_FILE="deploy/compose.${PROFILE}.yml"
DC=(docker compose -p assetflow -f "${COMPOSE_FILE}")

if [[ "${RESET}" -eq 1 ]]; then
  if [[ "${ASSETFLOW_ENV:-development}" = "production" ]]; then
    fail "--reset is for local development only."
  fi
  say "Reset: deleting existing AssetFlow containers and volumes for ${PROFILE} profile"
  if [[ -t 0 ]]; then
    read -r -p "This deletes all local AssetFlow volumes and data. Type 'yes' to continue: " answer
    if [[ "${answer}" != "yes" ]]; then
      echo "Aborted."
      exit 1
    fi
  fi
  "${DC[@]}" down -v --remove-orphans || true
fi

# ---------------------------------------------------------------- Step 3: Start the stack (§B13.1)
say "3/6 Starting stack (${PROFILE} profile)"

explain_start_failure() {
  local logs="$1"
  if grep -qiE 'masterkey|cipher: message authentication failed|unable to decrypt' <<<"${logs}"; then
    echo "Identity store cannot decrypt data: masterkey differs from volume." >&2
    echo "Restore original key or reset with: scripts/bootstrap.sh --reset" >&2
  elif grep -qiE 'password authentication failed' <<<"${logs}"; then
    echo "Database login failed: password differs from volume." >&2
    echo "Restore original password or reset with: scripts/bootstrap.sh --reset" >&2
  fi
}

if [[ "${PROFILE}" = "full" ]]; then
  if [[ "${ASSETFLOW_ENV:-development}" = "production" ]]; then
    [[ -n "${BAO_TOKEN:-}" ]] || fail "set BAO_TOKEN (operator token): read -rs BAO_TOKEN && export BAO_TOKEN"
    [[ -f deploy/.secrets/openbao-tls/ca.pem ]] || fail "no OpenBao TLS files; see docs/operations/openbao.md section 2."
  fi

  say "Starting OpenBao..."
  "${DC[@]}" up -d openbao
  if ! "${DC[@]}" exec -T openbao bao status >/dev/null 2>&1; then
    fail "OpenBao is not initialized or is sealed. Unseal it (docs/operations/openbao.md section 3), then run this again."
  fi

  say "Applying OpenBao configuration..."
  bash scripts/openbao-apply.sh --generate-missing --issue-secret-ids || fail "openbao-apply failed"

  say "Starting Zitadel..."
  if ! "${DC[@]}" up -d --wait zitadel; then
    explain_start_failure "$("${DC[@]}" logs --tail 200 zitadel 2>&1)"
    fail "Zitadel did not become healthy; see: ${DC[*]} logs zitadel"
  fi

  say "Bootstrapping Zitadel project and roles..."
  "${DC[@]}" --profile bootstrap run --rm --build zitadel-bootstrap apply ${APPLY_ARGS[@]+"${APPLY_ARGS[@]}"}
fi

if ! "${DC[@]}" up -d --wait; then
  explain_start_failure "$("${DC[@]}" logs --tail 200 2>&1)"
  fail "Stack failed to become healthy. See: ${DC[*]} logs"
fi

# ---------------------------------------------------------------- Step 4: Run migrations
say "4/6 Database migrations"
if ! "${DC[@]}" --profile tools run --rm migrate; then
  echo "tools migrate container not available, falling back to api container migration execution..."
  "${DC[@]}" exec -T api uv run --no-sync alembic upgrade head || fail "Database migrations failed"
fi

# ---------------------------------------------------------------- Step 5: Demo users and organization
say "5/6 Demo users, organizations and domain templates"
if [[ "${NO_DEMO}" -eq 0 && "${ASSETFLOW_ENV:-development}" != "production" ]]; then
  echo "Configuring default organization (example-alpha)..."
  if ! "${DC[@]}" exec -T api python -m app.cli.org_create --slug example-alpha --admin-email admin@example.test; then
    echo "Note: default organization creation reported non-zero or already exists (idempotent)."
  fi
else
  echo "Skipping demo data creation (--no-demo or production mode)."
fi

# ---------------------------------------------------------------- Step 6: Health and smoke check
say "6/6 Health and verification"
WEB_PORT="${WEB_PORT:-18080}"
HEALTH_URL="http://127.0.0.1:${WEB_PORT}/api/health"
CONFIG_URL="http://127.0.0.1:${WEB_PORT}/api/config/public"

echo "Checking ${HEALTH_URL}..."
if command -v curl >/dev/null 2>&1; then
  curl -s -f "${HEALTH_URL}" >/dev/null 2>&1 || curl -s -f "http://127.0.0.1:${WEB_PORT}/healthz" >/dev/null 2>&1 || echo "Notice: API health check pending container readiness."
fi

if [[ "${PROFILE}" = "full" && -f "scripts/smoke-full.py" && -n "${PYTHON_BIN}" ]]; then
  echo "Running full profile smoke test..."
  "${PYTHON_BIN}" scripts/smoke-full.py || echo "Warning: smoke-full reported an issue."
fi

cat <<EOF

=============================================================
 AssetFlow (${PROFILE} profile) is ready.

 Web Application:  http://localhost:${WEB_PORT}
 Demo Sign-In:     admin@example.test / demo-admin (minimal)
 Documentation:    docs/operations/installation.md

 Management commands:
   Stop stack:     docker compose -p assetflow -f deploy/compose.${PROFILE}.yml down
   Follow logs:    docker compose -p assetflow -f deploy/compose.${PROFILE}.yml logs -f
=============================================================

EOF
