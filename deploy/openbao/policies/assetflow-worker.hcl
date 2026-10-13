# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
# Policy: assetflow-worker (§B11.4, Decision 51)

# Read runtime secrets (own database role, smtp). The database credentials are split per role
# (AF-029): the worker reads database/worker only, never database/api.
path "secret/data/assetflow/database/worker" {
  capabilities = ["read"]
}

path "secret/data/assetflow/database/api" {
  capabilities = ["deny"]
}

path "secret/data/assetflow/smtp" {
  capabilities = ["read"]
}

# AF-029: no broad orgs/* read. Only per-organization channel credentials are readable.
# The channel runtime reads one installation's credentials at send time (§B6.3 rule 1); the worker
# never writes them (the api role does, write-only).
path "secret/data/assetflow/orgs/+/channels/*" {
  capabilities = ["read"]
}

# Explicit deny on the migrator credentials (deny wins over any other grant)
path "secret/data/assetflow/migrator" {
  capabilities = ["deny"]
}

# Field encryption/decryption for notification outbox & payloads
path "transit/encrypt/assetflow-fields" {
  capabilities = ["update"]
}

path "transit/decrypt/assetflow-fields" {
  capabilities = ["update"]
}
