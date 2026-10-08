<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# Runbook: re-key the OpenBao transit key as derived (AF-016)

The field-encryption key `transit/keys/assetflow-fields` must be created with `derived: true`, so
each organization encrypts under its own context and cannot decrypt another organization's data.
`scripts/openbao-apply.py` now creates the key derived, and **refuses** an existing non-derived key
with an error. OpenBao cannot turn a key into a derived one, so such a key must be deleted and
recreated.

## Who this affects

Only an environment whose `assetflow-fields` key was created before this change (non-derived), which
in practice means local development. **Data encrypted with the old key becomes unreadable** once the
key is recreated: encrypted custom fields and anything else written through the secrets provider's
encrypt call. Local test data can be dropped. Do not run this against an environment with data you
need; there is no migration path in this runbook.

## Steps (local development)

1. Stop the services that use the key (`make down`, or stop `af-api` and `af-worker`).
2. Confirm the key is non-derived: `bao read transit/keys/assetflow-fields` shows `derived` false
   (or `python scripts/openbao-apply.py` stops with the non-derived message).
3. Allow deletion, then delete the key (root or operator token):

   ```sh
   bao write transit/keys/assetflow-fields/config deletion_allowed=true
   bao delete transit/keys/assetflow-fields
   ```

4. Recreate it: `python scripts/openbao-apply.py --generate-missing` (see
   [OpenBao](../openbao.md)). The script creates the key with `derived: true`.
5. Remove or reset the local data that held ciphertext from the old key (for example reset the local
   database volume, or clear the encrypted custom field values), then start the services again.
6. Check: `bao read transit/keys/assetflow-fields` shows `derived` true.

## Rollback

None. The old key and the data encrypted with it are gone once deleted. Take a backup first if the
data matters ([backup and restore](../backup-restore.md)).
