# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
# Policy: assetflow-api (§B11.4, Decision 51)

# Read runtime secrets (own database role, idp, smtp). The database credentials are split per role
# (AF-029): the api reads database/api only, never database/worker.
path "secret/data/assetflow/database/api" {
  capabilities = ["read"]
}

path "secret/data/assetflow/database/worker" {
  capabilities = ["deny"]
}

path "secret/data/assetflow/idp" {
  capabilities = ["read"]
}

path "secret/data/assetflow/smtp" {
  capabilities = ["read"]
}

# The refresh-cookie signing key (app.api.policy.session_cookie_key, §B6.1 rule... session_cookie_key
# is required outside development/test). Only the api reads it; the worker never does.
path "secret/data/assetflow/session" {
  capabilities = ["read"]
}

# Channel credentials are write-only for the api (§B6.3 rule 1): the admin form can save or remove
# one, but nothing can read it back. There is deliberately no broader `orgs/*` stanza with `read`
# next to this one: when two paths both match, OpenBao's priority rules could let the broader read
# win, so the channel path is the only per-organization path the api touches, and only to write.
path "secret/data/assetflow/orgs/+/channels/*" {
  capabilities = ["create", "update", "patch", "delete"]
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
