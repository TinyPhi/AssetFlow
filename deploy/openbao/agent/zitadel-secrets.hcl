# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
# OpenBao Agent for Zitadel (§B5.5, §B11.4, decision 51).
# Reference: https://openbao.org/docs/agent-and-proxy/agent/
# Logs in with the zitadel AppRole (role id and secret id are mounted files), renders
# Zitadel's masterkey, database passwords and first-admin password into a tmpfs volume,
# and keeps running so the tmpfs volume stays mounted and rotated values are
# re-rendered (§B11.4 step 4). Nothing is written to environment variables, .env files or images.

vault {
  address = "https://openbao:8200"
  ca_cert = "/run/secrets/openbao_ca"
}

auto_auth {
  method "approle" {
    config = {
      role_id_file_path                   = "/run/secrets/zitadel_role_id"
      secret_id_file_path                 = "/run/secrets/zitadel_secret_id"
      remove_secret_id_file_after_reading = false
    }
  }
}

template_config {
  exit_on_retry_failure = true
}

# Masterkey: exactly 32 characters, no trailing newline (read with --masterkeyFile).
template {
  destination = "/rendered/masterkey"
  perms       = "0440"
  contents    = "{{ with secret \"secret/data/assetflow/zitadel/masterkey\" }}{{ .Data.data.value }}{{ end }}"
}

# Zitadel database users (merged over deploy/zitadel/config.yaml with a second --config).
template {
  destination = "/rendered/zitadel-secrets.yaml"
  perms       = "0440"
  contents    = <<-EOT
    {{ with secret "secret/data/assetflow/zitadel/database" }}
    Database:
      Postgres:
        User:
          Password: {{ .Data.data.user_password | toJSON }}
        Admin:
          Password: {{ .Data.data.admin_password | toJSON }}
    {{ end }}
  EOT
}

# Superuser password for the separate zitadel-db container (POSTGRES_PASSWORD_FILE).
template {
  destination = "/rendered/zitadel-db-admin-password"
  perms       = "0440"
  contents    = "{{ with secret \"secret/data/assetflow/zitadel/database\" }}{{ .Data.data.admin_password }}{{ end }}"
}

# First-instance admin password (merged over deploy/zitadel/steps.yaml with a second --steps).
template {
  destination = "/rendered/zitadel-steps-secrets.yaml"
  perms       = "0440"
  contents    = <<-EOT
    {{ with secret "secret/data/assetflow/zitadel/admin" }}
    FirstInstance:
      Org:
        Human:
          Password: {{ .Data.data.initial_password | toJSON }}
    {{ end }}
  EOT
}
