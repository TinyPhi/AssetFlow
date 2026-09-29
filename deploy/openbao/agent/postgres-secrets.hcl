# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
# OpenBao Agent for the AssetFlow PostgreSQL container (§B11.4, decision 51).
# Reference: https://openbao.org/docs/agent-and-proxy/agent/
# Renders the superuser password for POSTGRES_PASSWORD_FILE into a tmpfs volume and
# keeps running, so the volume stays mounted and a rotated value is re-rendered (§B11.4).

vault {
  address = "https://openbao:8200"
  ca_cert = "/run/secrets/openbao_ca"
}

auto_auth {
  method "approle" {
    config = {
      role_id_file_path                   = "/run/secrets/postgres_role_id"
      secret_id_file_path                 = "/run/secrets/postgres_secret_id"
      remove_secret_id_file_after_reading = false
    }
  }
}

template_config {
  exit_on_retry_failure = true
}

template {
  destination = "/rendered/postgres-superuser-password"
  perms       = "0440"
  contents    = "{{ with secret \"secret/data/assetflow/postgres\" }}{{ .Data.data.superuser_password }}{{ end }}"
}
