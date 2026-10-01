# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
# Policy: assetflow-postgres (§B11.4, decision 51). Used by the postgres-secrets agent only,
# to render the PostgreSQL superuser password file at container start.

path "secret/data/assetflow/postgres" {
  capabilities = ["read"]
}
