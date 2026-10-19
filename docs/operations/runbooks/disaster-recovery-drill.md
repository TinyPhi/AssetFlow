<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# Runbook: Quarterly Disaster Recovery Drill

**Frequency:** Every 90 days (§B13.5, §B13.6).  
**Objective:** Validate that the off-site backup, write-once copy, key retrieval, and restoration procedure achieve the RPO (< 5 min) and RTO (< 4 hours) targets.

## Checklist

1. [ ] **Key Custodian Attendance:** Ensure both designated security officers are present to unlock the encrypted key archive.
2. [ ] **Isolated Test Environment:** Spin up clean VM or host with no pre-existing AssetFlow volumes.
3. [ ] **Fetch Off-Site Backup:** Pull latest full and differential snapshots from S3.
4. [ ] **Execute Restore:**
   ```bash
   scripts/restore.sh --keys /secure/path/keys-archive.tar.gz --target latest
   ```
5. [ ] **Measure RTO:** Record elapsed time from start of command to health check readiness (Target: < 4 hours).
6. [ ] **Run Canary Check:**
   ```bash
   docker compose -p assetflow -f deploy/compose.minimal.yml exec -T api python -m app.cli.ops_canary check
   ```
7. [ ] **Audit Sign-off:** Sign and store the drill audit log in the compliance records.
