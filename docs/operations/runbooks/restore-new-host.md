<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# Runbook: Restoring AssetFlow to a New Host

**Scenario:** Complete loss of primary infrastructure or hardware migration to a clean host (§B13.5, §B13.6).

## Prerequisites

1. New host provisioned with Docker and Docker Compose v2.
2. Cloned AssetFlow repository.
3. Access to off-site S3 backup bucket and credentials.
4. Encrypted key archive provided by key custodians.

## Procedure

1. **Configure Environment:**
   Set S3 endpoint and repository credentials in `.env.local`:
   ```bash
   BACKUP_S3_ENDPOINT="s3.region.amazonaws.com"
   BACKUP_S3_BUCKET="assetflow-backups-primary"
   BACKUP_S3_KEY="<s3-access-key>"
   BACKUP_S3_SECRET="<s3-secret-key>"
   ```

2. **Execute Restoration:**
   ```bash
   scripts/restore.sh --keys /secure/path/keys-archive.tar.gz --target latest
   ```

3. **Verify Health and Decryption:**
   ```bash
   # Verify health endpoint
   curl -f http://localhost:18080/api/health

   # Run field encryption canary
   docker compose -p assetflow -f deploy/compose.minimal.yml exec -T api python -m app.cli.ops_canary check
   ```

4. **Post-Recovery Sign-off:**
   Log restore completion time, measured RTO, and canary check status in the operational incident record.
