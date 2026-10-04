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

# Channel credentials are write-only for the api (§B6.3 rule 1): the admin form can save or remove
# one, but nothing can read it back. There is deliberately no broader `orgs/*` stanza with `read`
# next to this one: when two paths both match, OpenBao's priority rules could let the broader read
# win, so the channel path is the only per-organization path the api touches, and only to write.
path "secret/data/assetflow/orgs/+/channels/*" {
  capabilities = ["create", "update", "delete"]
}

path "secret/metadata/assetflow/orgs/+/channels/*" {
  capabilities = ["delete"]
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
