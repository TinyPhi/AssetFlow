# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
# OpenBao server configuration for LOCAL DEVELOPMENT only (deploy/compose.dev.yml, `make dev`).
# Server mode with file storage, so data and the transit key survive restarts (the dev-mode
# server keeps everything in memory and would make encrypted fields unreadable). No TLS: the
# listener is reachable only on the compose network and on 127.0.0.1 of the host. Production uses
# deploy/openbao/config/openbao.hcl (Raft, TLS, manual unseal).
# Reference: https://openbao.org/docs/configuration/

ui = false
disable_mlock = true

storage "file" {
  path = "/openbao/file"
}

listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = true
}

api_addr = "http://openbao:8200"

default_lease_ttl = "1h"
max_lease_ttl     = "768h"

# No file audit device here: OpenBao 2.x refuses to enable one over the API
# ("use declarative, config-based audit device management instead"), and this project's config
# key for that is not yet documented upstream; scripts/openbao-apply.py (audit_device) logs a
# warning and continues rather than failing the local stack over it. Production
# (deploy/openbao/config/openbao.hcl) has the same gap; see docs/operations/openbao.md.
