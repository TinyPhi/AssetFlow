#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
# pgBackRest backup scheduler and metrics exporter (§B13.5, M1.6-T9).
#
# pgBackRest reads its config file literally: it does not expand `${VAR}`. So the daemon renders
# the mounted template into a private file on tmpfs first (defaults applied here, values checked),
# and every pgBackRest call uses that file through PGBACKREST_CONFIG.
#
# Metrics are measured, never assumed: the last backup and the restorable point come from
# `pgbackrest info`, the WAL archive lag from PostgreSQL's `pg_stat_archiver`. Anything that cannot
# be measured counts from the daemon's start, so a monitor that keeps failing raises the alerts
# instead of hiding them. BACKUP_DAEMON_ONCE=1 renders, measures once and exits (used by tests).

set -euo pipefail

TEMPLATE="${PGBACKREST_TEMPLATE:-/etc/pgbackrest/pgbackrest.conf.template}"
export PGBACKREST_CONFIG="${PGBACKREST_CONFIG:-/tmp/pgbackrest.conf}"
METRICS_DIR="${BACKUP_METRICS_DIR:-/var/spool/pgbackrest/metrics}"
STANZA="assetflow"
DAEMON_START="$(date +%s)"

# Defaults for the optional settings; the credentials have none (compose refuses to start without).
: "${BACKUP_S3_ENDPOINT:=s3.amazonaws.com}"
: "${BACKUP_S3_BUCKET:=assetflow-backups}"
: "${BACKUP_S3_REGION:=us-east-1}"
: "${BACKUP_WORM_ENDPOINT:=${BACKUP_S3_ENDPOINT}}"
: "${BACKUP_WORM_BUCKET:=assetflow-backups-worm}"
: "${BACKUP_WORM_REGION:=${BACKUP_S3_REGION}}"
: "${BACKUP_WORM_KEY:=${BACKUP_S3_KEY:-}}"
: "${BACKUP_WORM_SECRET:=${BACKUP_S3_SECRET:-}}"
: "${POSTGRES_HOST:=postgres}"
: "${POSTGRES_PORT:=5432}"
: "${POSTGRES_USER:=assetflow_app}"
: "${ZITADEL_DB_HOST:=zitadel-db}"

CONFIG_VARS=(
  BACKUP_S3_ENDPOINT BACKUP_S3_BUCKET BACKUP_S3_REGION BACKUP_S3_KEY BACKUP_S3_SECRET
  BACKUP_CIPHER_PASS
  BACKUP_WORM_ENDPOINT BACKUP_WORM_BUCKET BACKUP_WORM_REGION BACKUP_WORM_KEY BACKUP_WORM_SECRET
  POSTGRES_HOST POSTGRES_PORT POSTGRES_USER ZITADEL_DB_HOST
)
REQUIRED_VARS=(BACKUP_S3_KEY BACKUP_S3_SECRET BACKUP_CIPHER_PASS)

render_config() {
  local name shell_format=""
  for name in "${REQUIRED_VARS[@]}"; do
    if [[ -z "${!name:-}" ]]; then
      echo "error: ${name} is not set; refusing to render the pgBackRest config" >&2
      exit 1
    fi
  done
  for name in "${CONFIG_VARS[@]}"; do
    # One value per line: a newline would let a value add its own config lines.
    if [[ "${!name}" == *$'\n'* || "${!name}" == *$'\r'* ]]; then
      echo "error: ${name} contains a line break" >&2
      exit 1
    fi
    export "${name?}"
    shell_format+="\${${name}} "
  done
  # Only the listed variables are replaced; the rendered file holds secrets, so it is owner-only.
  (umask 077 && envsubst "${shell_format}" <"${TEMPLATE}" >"${PGBACKREST_CONFIG}.tmp")
  mv "${PGBACKREST_CONFIG}.tmp" "${PGBACKREST_CONFIG}"
  if grep -q '\${' "${PGBACKREST_CONFIG}"; then
    echo "error: the rendered pgBackRest config still has unexpanded variables" >&2
    exit 1
  fi
}

write_metrics() {
  local last_success="$1" wal_lag="$2" restorable_age="$3" repo_used_ratio="$4"
  mkdir -p "${METRICS_DIR}"
  {
    echo "# HELP assetflow_backup_last_success_timestamp_seconds Epoch seconds of the newest completed backup (0 = none)"
    echo "# TYPE assetflow_backup_last_success_timestamp_seconds gauge"
    echo "assetflow_backup_last_success_timestamp_seconds ${last_success}"
    echo "# HELP assetflow_backup_wal_archive_lag_seconds Seconds since PostgreSQL last archived a WAL segment"
    echo "# TYPE assetflow_backup_wal_archive_lag_seconds gauge"
    echo "assetflow_backup_wal_archive_lag_seconds ${wal_lag}"
    echo "# HELP assetflow_backup_restorable_point_age_seconds Age in seconds of the newest restorable recovery point"
    echo "# TYPE assetflow_backup_restorable_point_age_seconds gauge"
    echo "assetflow_backup_restorable_point_age_seconds ${restorable_age}"
    # Object storage has no capacity of its own: the ratio is reported only against a set quota.
    if [[ -n "${repo_used_ratio}" ]]; then
      echo "# HELP assetflow_backup_repo_used_ratio Backup repository size over BACKUP_REPO_QUOTA_BYTES (0.0 to 1.0)"
      echo "# TYPE assetflow_backup_repo_used_ratio gauge"
      echo "assetflow_backup_repo_used_ratio ${repo_used_ratio}"
    fi
  } >"${METRICS_DIR}/backup.prom.tmp"
  mv "${METRICS_DIR}/backup.prom.tmp" "${METRICS_DIR}/backup.prom"
}

# Epoch seconds of PostgreSQL's last archived WAL segment, or empty when it cannot be read.
last_archived_wal() {
  PGCONNECT_TIMEOUT=5 psql -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT}" -U "${POSTGRES_USER}" \
    -d "${POSTGRES_DB:-postgres}" -XAtqc \
    "SELECT COALESCE(EXTRACT(EPOCH FROM last_archived_time)::bigint, 0) FROM pg_stat_archiver" \
    2>/dev/null || true
}

collect_metrics() {
  local now info last_success=0 repo_bytes=0 archived ratio="" newest_point wal_lag restorable_age
  now="$(date +%s)"
  if info="$(pgbackrest info --output=json --stanza="${STANZA}" 2>/dev/null)"; then
    last_success="$(jq -r '[.[0].backup[]?.timestamp.stop] | max // 0' <<<"${info}" 2>/dev/null || echo 0)"
    repo_bytes="$(jq -r '[.[0].backup[]?.info.repository.delta // 0] | add // 0' <<<"${info}" 2>/dev/null || echo 0)"
  fi

  archived="$(last_archived_wal)"
  if [[ "${archived}" =~ ^[0-9]+$ && "${archived}" -gt 0 ]]; then
    wal_lag=$((now - archived))
  else
    wal_lag=$((now - DAEMON_START))  # never archived, or unreadable: unknown counts as stale
    archived=0
  fi

  newest_point=$((last_success > archived ? last_success : archived))
  if [[ "${newest_point}" -gt 0 ]]; then
    restorable_age=$((now - newest_point))
  else
    restorable_age=$((now - DAEMON_START))
  fi

  if [[ "${BACKUP_REPO_QUOTA_BYTES:-}" =~ ^[1-9][0-9]*$ ]]; then
    ratio="$(awk -v used="${repo_bytes}" -v quota="${BACKUP_REPO_QUOTA_BYTES}" 'BEGIN { printf "%.4f", used / quota }')"
  fi

  write_metrics "${last_success}" "${wal_lag}" "${restorable_age}" "${ratio}"
}

render_config
collect_metrics
if [[ "${BACKUP_DAEMON_ONCE:-0}" == "1" ]]; then
  exit 0
fi

echo "Starting pgBackRest backup daemon..."

# Main scheduling loop
while true; do
  current_day=$(date +%u) # 1 = Monday, 7 = Sunday
  current_hour=$(date +%H)
  current_min=$(date +%M)

  # Full backup every Sunday at 02:00, differential backup on other days at 02:00
  if [[ "${current_hour}" == "02" && "${current_min}" == "00" ]]; then
    if [[ "${current_day}" == "7" ]]; then
      echo "Executing weekly full backup..."
      pgbackrest --stanza="${STANZA}" backup --type=full || echo "error: full backup failed"
    else
      echo "Executing daily differential backup..."
      pgbackrest --stanza="${STANZA}" backup --type=diff || echo "error: diff backup failed"
    fi
    echo "Verifying backup repository..."
    pgbackrest --stanza="${STANZA}" verify || echo "error: backup verification failed"
    collect_metrics
  elif ((10#${current_min} % 5 == 0)); then
    collect_metrics  # every five minutes, so the lag and age alerts see fresh values
  fi

  sleep 60
done
