<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# Tutorial: First Installation & Organization Setup

This tutorial walks through setting up AssetFlow on a new workstation from scratch (§B13.1, M1.6-T8).

## Step 1: Clone and Verify Tools

Ensure Docker and Docker Compose v2 are installed and operational:

```bash
docker --version
docker compose version
```

Clone the repository:
```bash
git clone https://github.com/tinyphi/assetflow.git
cd assetflow
```

## Step 2: Run Bootstrap

Execute the bootstrap script to create the local development environment:

```bash
# On Linux / macOS / WSL2:
scripts/bootstrap.sh

# On Windows PowerShell / Command Prompt:
setup.bat
```

The script will:
1. Verify preflight conditions (Docker Compose v2, available host ports, disk space).
2. Generate local database passwords and encryption keys into `.secrets/`.
3. Launch the container stack defined in `deploy/compose.minimal.yml`.
4. Run Alembic database migrations.
5. Create the default organization `example-alpha` and assign its initial administrator.
6. Verify API health endpoints.

## Step 3: Sign In to the Web Shell

Open your browser to:
```
http://localhost:18080
```

Sign in with:
- **Email:** `admin@example.test`
- **Password:** `demo-admin`

## Step 4: Explore Organization and Access

From the left navigation bar:
- **Dashboard:** Review system overview and metrics.
- **Organization Units:** Inspect the divisional hierarchy.
- **Teams & Members:** View member directories, team assignments, and scoped role grants.
- **Access View Matrix:** Inspect effective tenant permissions calculated across scopes.
- **Modules:** Verify that `assets` and `maintenance` modules are installed and operational.

## Next Steps

- Consult the [Testing Guide](../guides/testing.md) to understand authorization matrix tests.
- Learn about configuring notification channels in [Writing a Notification Channel](../guides/writing-a-notification-channel.md).
- Review [Operations Runbooks](../operations/README.md) for production deployment instructions.
