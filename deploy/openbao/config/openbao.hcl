# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
# OpenBao server configuration for AssetFlow (§B11.4, decision 51).
# Reference: https://openbao.org/docs/configuration/
# Production mode only: no -dev flag. Init and unseal: docs/operations/openbao.md.
# The container entrypoint loads every file in /openbao/config, so keep only this file there.

ui = false

# Raft integrated storage (https://openbao.org/docs/configuration/storage/raft/).
# The docs recommend disable_mlock with Raft storage.
disable_mlock = true

storage "raft" {
  path    = "/openbao/file"
  node_id = "assetflow-openbao-1"
}

# TLS listener (https://openbao.org/docs/configuration/listener/tcp/).
# Certificate files are mounted by compose as secrets; see docs/operations/openbao.md.
listener "tcp" {
  address         = "0.0.0.0:8200"
  cluster_address = "0.0.0.0:8201"
  tls_disable     = false
  tls_cert_file   = "/run/secrets/openbao_tls_cert"
  tls_key_file    = "/run/secrets/openbao_tls_key"
  tls_min_version = "tls12"
}

api_addr     = "https://openbao:8200"
cluster_addr = "https://openbao:8201"

default_lease_ttl = "1h"
max_lease_ttl     = "768h"
