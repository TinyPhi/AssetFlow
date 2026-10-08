# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
# Policy: assetflow-migrator (§B11.4, decision 51). Read-only.

# Migration (DDL) role credentials
path "secret/data/assetflow/migrator" {
  capabilities = ["read"]
}

# Runtime role credentials, so migrations can grant them
path "secret/data/assetflow/database/api" {
  capabilities = ["read"]
}

path "secret/data/assetflow/database/worker" {
  capabilities = ["read"]
}
