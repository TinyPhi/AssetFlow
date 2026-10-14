<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# Getting Started with AssetFlow

This guide gets you up and running with a local AssetFlow environment in minutes (§B13.1, M1.6-T8).

## Prerequisites

- **Docker Desktop** or **Docker Engine** (24.0+) with **Docker Compose v2** (`docker compose version`)
- **Git**
- Optional: **Python 3.10+** (if running host tools or tests outside containers)

## Quick Start (Minimal Profile)

AssetFlow provides a single-command bootstrap that checks preflight conditions, generates local secrets into `.secrets/`, starts the containers, applies database migrations, and initializes the demo organization.

### Linux / macOS / WSL2

```bash
# Clone the repository
git clone https://github.com/tinyphi/assetflow.git
cd assetflow

# Run bootstrap (default profile: minimal)
scripts/bootstrap.sh
```

### Windows (PowerShell / Command Prompt)

```bat
# From repository root
setup.bat
```

## Accessing the Web Application

Once bootstrap completes:

1. Open your browser and navigate to:
   **`http://localhost:18080`**
2. Sign in using the pre-configured demo account:
   - **Email:** `admin@example.test`
   - **Password:** `demo-admin`
3. You will land on the AssetFlow Dashboard with pre-configured sample organization structures.

## Managing the Stack

- **Stop containers:**
  ```bash
  docker compose -p assetflow -f deploy/compose.minimal.yml down
  ```
- **View container logs:**
  ```bash
  docker compose -p assetflow -f deploy/compose.minimal.yml logs -f
  ```
- **Reset all local data and re-bootstrap:**
  ```bash
  scripts/bootstrap.sh --reset
  ```
