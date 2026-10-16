<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# Backup and Recovery Architecture

AssetFlow implements database and key backup following the **3-2-1-1 rule** (§B13.5, M1.6-T9):
- **3 copies** of data: production database, primary off-site repository, and immutable copy.
- **2 different media/stores**: local PostgreSQL storage and cloud object store (S3-compatible).
- **1 off-site**: cloud object store in an isolated availability zone/region.
- **1 immutable write-once copy**: S3 bucket with Object Lock in compliance mode.

---

## Recovery Targets (§B13.5)

- **Recovery Point Objective (RPO):** Maximum **5 minutes** of data loss. Enforced by PostgreSQL WAL archiving with `archive_timeout = 60` seconds.
- **Recovery Time Objective (RTO):** Maximum **4 hours** to full single-node restoration.

---

## Retention Policy (§B13.5)

| Backup Type | Frequency | Retention Period |
|---|---|---|
| Continuous WAL Archive | Every 60 seconds | 14 days |
| Differential Backup | Daily at 02:00 UTC | 14 days |
| Full Backup | Weekly (Sunday at 02:00 UTC) | 8 weeks |
| Monthly Snapshot | Monthly archive | 12 months |

---

## Cryptographic Key Protection (§B11.4, §B13.5)

> [!CAUTION]
> **Cardinal Rule:** Always restore cryptographic keys BEFORE restoring the database. A restored database without matching encryption keys is unreadable.

- All backups are encrypted using **AES-256-CBC** before leaving the host.
- The backup cipher passphrase (`secret://backup/repo#cipher_pass`) and field encryption keys are backed up into an encrypted archive held by two designated security custodians.
- Keys must **never** be stored in the same repository or bucket as database backups.

---

## Restoring from Backup

To perform a complete restoration:

```bash
# Provide path to the custodians' keys archive and optional recovery target timestamp
scripts/restore.sh --keys /path/to/keys-archive.tar.gz --target latest

# Or for point-in-time recovery:
scripts/restore.sh --keys /path/to/keys-archive.tar.gz --target "2026-10-04 14:30:00"
```

The restore script automatically:
1. Restores `.secrets/` cryptographic keys.
2. Stops active application workers.
3. Invokes `pgbackrest restore` inside the `backup` container.
4. Starts the application stack.
5. Runs the field decryption canary check (`assetflow ops canary check`).
6. Computes and logs elapsed recovery time.

---

## Automated Monthly Restore Drill

A monthly automated restore test (`scripts/restore-test.sh`) runs inside an isolated environment (`assetflow-restoretest`):
- Restores latest snapshot into a throwaway database.
- Verifies field-level encryption canary.
- Compares record counts per table.
- Emits Prometheus metric `assetflow_backup_restore_test_last_success_timestamp_seconds`.
- Completely cleans up all temporary test containers.
