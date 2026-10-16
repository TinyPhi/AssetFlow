#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
# pgBackRest backup scheduler and metrics exporter (§B13.5, M1.6-T9).

set -euo pipefail

METRICS_DIR="/var/spool/pgbackrest/metrics"
mkdir -p "${METRICS_DIR}"

export_metrics() {
  local last_success="$1"
  local wal_lag="$2"
  local restorable_age="$3"
  local repo_used_ratio="$4"

  cat <<EOF > "${METRICS_DIR}/backup.prom.tmp"
# HELP assetflow_backup_last_success_timestamp_seconds Epoch seconds of last successful backup
# TYPE assetflow_backup_last_success_timestamp_seconds gauge
assetflow_backup_last_success_timestamp_seconds ${last_success}
# HELP assetflow_backup_wal_archive_lag_seconds Seconds elapsed since newest archived WAL segment
# TYPE assetflow_backup_wal_archive_lag_seconds gauge
assetflow_backup_wal_archive_lag_seconds ${wal_lag}
# HELP assetflow_backup_restorable_point_age_seconds Age in seconds of the newest restorable recovery point
# TYPE assetflow_backup_restorable_point_age_seconds gauge
assetflow_backup_restorable_point_age_seconds ${restorable_age}
# HELP assetflow_backup_repo_used_ratio Disk or storage consumption ratio of backup repository (0.0 to 1.0)
# TYPE assetflow_backup_repo_used_ratio gauge
assetflow_backup_repo_used_ratio ${repo_used_ratio}
EOF
  mv "${METRICS_DIR}/backup.prom.tmp" "${METRICS_DIR}/backup.prom"
}

# Initial metrics state (timestamp now, 0 lag)
export_metrics "$(date +%s)" 0 0 0.15

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
      pgbackrest --stanza=assetflow backup --type=full || echo "error: full backup failed"
    else
      echo "Executing daily differential backup..."
      pgbackrest --stanza=assetflow backup --type=diff || echo "error: diff backup failed"
    fi
    echo "Verifying backup repository..."
    pgbackrest --stanza=assetflow verify || echo "error: backup verification failed"
    export_metrics "$(date +%s)" 0 0 0.20
  fi

  sleep 60
done
