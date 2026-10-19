# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
# Policy: assetflow-operator (§B11.4, decision 51).
# For the human operator running scripts/openbao-apply.py and scripts/bootstrap_zitadel.py after
# bootstrap, so the root token can be revoked. Not attached to any AppRole.

# Engines and auth methods used by AssetFlow
path "sys/mounts" {
  capabilities = ["read"]
}
path "sys/mounts/secret" {
  capabilities = ["create", "read", "update"]
}
path "sys/mounts/transit" {
  capabilities = ["create", "read", "update"]
}
path "sys/auth" {
  capabilities = ["read"]
}
path "sys/auth/approle" {
  capabilities = ["create", "read", "update", "sudo"]
}

# Policies (ACL) managed from deploy/openbao/policies and deploy/openbao/operator. Only names starting
# with assetflow- (AF-030): the operator cannot rewrite `default`, `root` or any other policy.
path "sys/policies/acl/assetflow-*" {
  capabilities = ["create", "read", "update"]
}
path "sys/policies/acl" {
  capabilities = ["list"]
}

# File audit device (enabled by scripts/openbao-apply.py; the operator cannot disable it)
path "sys/audit" {
  capabilities = ["read", "sudo"]
}
path "sys/audit/file" {
  capabilities = ["create", "update", "sudo"]
}

# AppRole roles, role ids and secret ids
path "auth/approle/role/assetflow-*" {
  capabilities = ["create", "read", "update", "list"]
}

# Transit key for field encryption (no delete, no export)
path "transit/keys/assetflow-fields" {
  capabilities = ["create", "read", "update"]
}
path "transit/keys/assetflow-fields/config" {
  capabilities = ["update"]
}
path "transit/keys/assetflow-fields/rotate" {
  capabilities = ["update"]
}

# AssetFlow secrets (write and rotate values; applications only read)
path "secret/data/assetflow/*" {
  capabilities = ["create", "read", "update"]
}
path "secret/metadata/assetflow/*" {
  capabilities = ["read", "list"]
}

# Health and seal status
path "sys/health" {
  capabilities = ["read", "sudo"]
}
