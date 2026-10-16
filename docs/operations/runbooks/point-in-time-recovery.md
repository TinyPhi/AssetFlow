<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# Runbook: Point-in-Time Recovery (PITR)

**Scenario:** Reverting accidental tenant data corruption or bad migration to a specific historical timestamp (§B13.5, §B13.6).

## Procedure

1. **Identify Recovery Timestamp:**
   Determine the exact target time prior to the incident in UTC format: `YYYY-MM-DD HH:MM:SS`.

2. **Execute PITR Recovery:**
   ```bash
   scripts/restore.sh --keys /secure/path/keys-archive.tar.gz --target "2026-10-04 14:30:00"
   ```

3. **Verify Restored State:**
   - Confirm WAL replay stopped at or before requested timestamp.
   - Run `python -m app.cli.ops_canary check` to ensure field decryption integrity.
   - Inspect affected tenant records to confirm corrupted state is resolved.
