# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
# Policy: zitadel (§B5.5, §B11.4, decision 51). Used by the zitadel-secrets agent only.
# Read-only on Zitadel's own secrets; never the automation key or AssetFlow paths.

path "secret/data/assetflow/zitadel/masterkey" {
  capabilities = ["read"]
}

path "secret/data/assetflow/zitadel/database" {
  capabilities = ["read"]
}

path "secret/data/assetflow/zitadel/admin" {
  capabilities = ["read"]
}
