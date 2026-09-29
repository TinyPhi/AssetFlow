# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
# Policy: assetflow-api (§B11.4, Decision 51)

# Read runtime secrets (database, idp, smtp)
path "secret/data/assetflow/database" {
  capabilities = ["read"]
}

path "secret/data/assetflow/idp" {
  capabilities = ["read"]
}

path "secret/data/assetflow/smtp" {
  capabilities = ["read"]
}

# Read organization and channel secrets
path "secret/data/assetflow/orgs/*" {
  capabilities = ["read"]
}

# Explicit deny on the migrator credentials (deny wins over any other grant)
path "secret/data/assetflow/migrator" {
  capabilities = ["deny"]
}

# Application-level field encryption via transit engine
path "transit/encrypt/assetflow-fields" {
  capabilities = ["update"]
}

path "transit/decrypt/assetflow-fields" {
  capabilities = ["update"]
}
