#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
#
# AssetFlow database and keys restoration script (§B11.4, §B13.5, M1.6-T9).
# Restores cryptographic keys first, then restores database via pgBackRest,
# verifies field encryption canary, and measures recovery time (RTO).
# Every step must succeed: the first failure stops the restore with an error and a non-zero exit,
# and "Restore completed successfully" is printed only when every step, canary included, passed.
#
# Usage:
#   scripts/restore.sh --keys <path-to-keys.tar.gz> [--target latest|<timestamp>] [--profile minimal|full]
#   make restore KEYS=<path-to-keys.tar.gz> [TARGET=latest|<timestamp>]

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"
export MSYS_NO_PATHCONV=1

TARGET="latest"
KEYS_ARCHIVE=""
PROFILE="minimal"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)
      TARGET="${2:-}"
      shift 2
      ;;
    --target=*)
      TARGET="${1#*=}"
      shift
      ;;
    --keys)
      KEYS_ARCHIVE="${2:-}"
      shift 2
      ;;
    --keys=*)
      KEYS_ARCHIVE="${1#*=}"
      shift
      ;;
    --profile)
      PROFILE="${2:-minimal}"
      shift 2
      ;;
    --profile=*)
      PROFILE="${1#*=}"
      shift
      ;;
    -h|--help)
      sed -n '4,15p' "$0"
      exit 0
      ;;
    TARGET=*)
      TARGET="${1#*=}"
      shift
      ;;
    KEYS=*)
      KEYS_ARCHIVE="${1#*=}"
      shift
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "${KEYS_ARCHIVE}" ]]; then
  echo "error: missing required --keys argument (path to encrypted keys archive)" >&2
  echo "Usage: scripts/restore.sh --keys <keys-archive> [--target latest|<timestamp>]" >&2
  exit 2
fi

if [[ ! -f "${KEYS_ARCHIVE}" ]]; then
  echo "error: keys archive not found at: ${KEYS_ARCHIVE}" >&2
  exit 1
fi

say() { printf '\n==> %s\n' "$1"; }
fail() { printf '\nerror: %s\n' "$1" >&2; exit 1; }

START_TIME=$(date +%s)

# ---------------------------------------------------------------- Step 1: Restore Keys First (§B11.4)
say "1/4 Restoring cryptographic keys and secrets"
SECRETS_DIR="${RESTORE_SECRETS_DIR:-.secrets}"
mkdir -p "${SECRETS_DIR}"
echo "Extracting keys from ${KEYS_ARCHIVE}..."
tar -xzf "${KEYS_ARCHIVE}" -C "${SECRETS_DIR}" 2>/dev/null || tar -xf "${KEYS_ARCHIVE}" -C "${SECRETS_DIR}" ||
  fail "could not extract the keys archive ${KEYS_ARCHIVE}"
chmod -R 600 "${SECRETS_DIR}"/* 2>/dev/null || true

# ---------------------------------------------------------------- Step 2: Database Restore via pgBackRest
say "2/4 Restoring database from backup repository (target: ${TARGET})"
COMPOSE_FILE="deploy/compose.${PROFILE}.yml"
BACKUP_COMPOSE="deploy/compose.backup.yml"
DC=(docker compose -p assetflow -f "${COMPOSE_FILE}" -f "${BACKUP_COMPOSE}")

# Stop API and workers before database restore to prevent data modification
echo "Stopping application services..."
"${DC[@]}" stop api worker || fail "could not stop api and worker; refusing to restore under live writes"

RESTORE_ARGS=("--stanza=assetflow")
if [[ "${TARGET}" != "latest" ]]; then
  RESTORE_ARGS+=("--type=time" "--target=${TARGET}")
fi

echo "Invoking pgbackrest restore inside af-backup container..."
"${DC[@]}" exec -T backup pgbackrest "${RESTORE_ARGS[@]}" restore || fail "pgBackRest restore failed"

# ---------------------------------------------------------------- Step 3: Restart Application Stack
say "3/4 Starting application stack with restored data"
"${DC[@]}" up -d --wait api worker web || fail "the application stack did not come back healthy"

# ---------------------------------------------------------------- Step 4: Canary & Integrity Verification
say "4/4 Verifying restore canary and decryption capability"
if command -v python3 >/dev/null 2>&1; then
  PY_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PY_BIN="python"
else
  PY_BIN=""
fi

if [[ -z "${PY_BIN}" || ! -f "backend/app/cli/ops_canary.py" ]]; then
  fail "the canary check could not run (no Python or no ops_canary); the restore is unverified"
fi
echo "Running ops canary verification check..."
(cd backend && "${PY_BIN}" -m app.cli.ops_canary check --org-slug example-alpha) ||
  fail "canary check failed: the restored keys do not decrypt the restored data"

END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))

cat <<EOF

=============================================================
 Restore completed successfully!
 Target:        ${TARGET}
 Keys Archive:  ${KEYS_ARCHIVE}
 Elapsed Time:  ${ELAPSED} seconds (RTO metric)
=============================================================

EOF
