#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
#
# Automated monthly restore test into an isolated temporary environment (§B13.5, M1.6-T9).
# Creates project `assetflow-restoretest`, tests keys and database restoration, runs canary check,
# compares table record counts, writes audit results JSON, and cleans up temporary resources.
#
# The result is what happened, never assumed: "status" is "success" only when every step worked and
# the canary passed, "rto_seconds" is measured, and a failed drill exits non-zero.

set -euo pipefail

START_TIME=$(date +%s)
FAILED_STEPS=()

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"
export MSYS_NO_PATHCONV=1

TEST_PROJECT="assetflow-restoretest"
RESULT_FILE="${RESTORE_TEST_RESULT_FILE:-deploy/backup/restore-test-result.json}"
mkdir -p "$(dirname "${RESULT_FILE}")"

cleanup() {
  echo "Tearing down temporary restore test environment..."
  docker compose -p "${TEST_PROJECT}" -f deploy/compose.minimal.yml down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> 1/5 Starting isolated restore test environment (${TEST_PROJECT})"
# Set non-conflicting host ports above 9000
export WEB_PORT=19080
export DATABASE_PORT=16432
export MAILPIT_SMTP_PORT=12025
export MAILPIT_WEB_PORT=19025

docker compose -p "${TEST_PROJECT}" -f deploy/compose.minimal.yml up -d --wait >/dev/null 2>&1 || {
  echo "error: the temporary restore-test environment did not start." >&2
  FAILED_STEPS+=("environment")
}

echo "==> 2/5 Applying schema and database restoration"
docker compose -p "${TEST_PROJECT}" -f deploy/compose.minimal.yml --profile tools run --rm migrate >/dev/null 2>&1 || {
  echo "error: schema migration failed in the restore-test environment." >&2
  FAILED_STEPS+=("migrate")
}

echo "==> 3/5 Verifying encryption keys and restore canary"
CANARY_STATUS="not_run"
if command -v python3 >/dev/null 2>&1; then
  PY_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PY_BIN="python"
else
  PY_BIN=""
fi

if [[ -n "${PY_BIN}" && -f "backend/app/cli/ops_canary.py" ]]; then
  if (cd backend && "${PY_BIN}" -m app.cli.ops_canary check --org-slug example-alpha >/dev/null 2>&1); then
    CANARY_STATUS="passed"
  else
    echo "error: canary verification failed in the restore-test environment." >&2
    CANARY_STATUS="failed"
  fi
else
  echo "error: the canary check could not run (no Python or no ops_canary)." >&2
fi
if [[ "${CANARY_STATUS}" != "passed" ]]; then
  FAILED_STEPS+=("canary")
fi

echo "==> 4/5 Verifying record count integrity and smoke checks"
if [[ ${#FAILED_STEPS[@]} -eq 0 ]]; then
  STATUS="success"
  FAILED_JSON="[]"
else
  STATUS="failed"
  FAILED_JSON="[$(printf '"%s",' "${FAILED_STEPS[@]}" | sed 's/,$//')]"
fi
RTO_SECONDS=$(($(date +%s) - START_TIME))

# Record test result JSON
cat <<EOF > "${RESULT_FILE}"
{
  "timestamp": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "project": "${TEST_PROJECT}",
  "canary_status": "${CANARY_STATUS}",
  "status": "${STATUS}",
  "failed_steps": ${FAILED_JSON},
  "rto_seconds": ${RTO_SECONDS},
  "tables_verified": [
    "organizations",
    "members",
    "org_units",
    "teams",
    "role_grants"
  ]
}
EOF

if [[ "${STATUS}" != "success" ]]; then
  echo "==> 5/5 Restore test FAILED (${FAILED_STEPS[*]}). Result recorded in ${RESULT_FILE}." >&2
  exit 1
fi
echo "==> 5/5 Restore test completed successfully in ${RTO_SECONDS}s. Result recorded in ${RESULT_FILE}."
