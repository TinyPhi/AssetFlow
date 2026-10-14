<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# Database Roles and Login Standard

This document details the PostgreSQL role model, login accounts, credential management, and rotation procedures for AssetFlow per [ADR-0019](../decisions/ADR-0019-database-roles-and-login-users.md) and master plan §B10/§B11.

---

## 1. Role Architecture

AssetFlow strictly separates privilege definitions (group roles) from authentication identities (login users).

### Group Roles (`NOLOGIN`)

Group roles define schema privileges and RLS enforcement. They cannot authenticate directly to PostgreSQL.

| Role | Login | Primary Privileges | RLS Status |
| --- | --- | --- | --- |
| `assetflow_api` | `NO` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` on tenant tables | Subject to RLS |
| `assetflow_worker` | `NO` | `SELECT`, `UPDATE` on outbox, sweep, background tasks | Subject to RLS |
| `assetflow_migrator` | `NO` | Schema object owner, DDL execution, Alembic migrations | `NOBYPASSRLS` |
| `assetflow_readonly` | `NO` | `SELECT` on tenant tables | Subject to RLS |
| `assetflow_resolver` | `NO` | Owns `platform.resolve_organization()`; isolated internal role | N/A |

All roles are created with:
```sql
NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION
```

### Login Users (`LOGIN`)

Application processes authenticate using dedicated login accounts matching the pattern `assetflow_<kind>_login`:

| Login User | Assigned Group Role | Purpose |
| --- | --- | --- |
| `assetflow_api_login` | `assetflow_api` | FastAPI application backend instances |
| `assetflow_worker_login` | `assetflow_worker` | Background task workers |
| `assetflow_migrator_login` | `assetflow_migrator` | One-shot migration container / Alembic runner |
| `assetflow_readonly_login` | `assetflow_readonly` | Read-only analytics or replica queries (created by an operator when needed; not part of the minimal profile) |

Login users inherit the permissions of their respective group roles via `GRANT <group_role> TO <login_user>;` and possess `CONNECT ON DATABASE <dbname>`.

---

## 2. Credential Management

- **Zero Hardcoded Secrets:** Passwords must never appear in compose files, environment defaults, container images, or git-tracked files.
- **Development Profile:** Passwords are generated via `scripts/gen-minimal-secrets.py` and stored in the git-ignored `.secrets/` directory (`.secrets/database/<kind>/password`), mounted into container services as read-only Docker secrets.
- **Production Profile:** Passwords are stored in and dynamically leased or retrieved from OpenBao (`secret://database/<kind>#password`).

---

## 3. Credential Rotation Runbook

To rotate a password for a login account:

1. **Update Secret Store:**
   - In development: update the secret file in `.secrets/database/<kind>/password`.
   - In production: write the new password into OpenBao at `secret/data/database/<kind>` under key `password`.

2. **Update PostgreSQL Role Password:**
   Connect to PostgreSQL as administrative user and execute:
   ```sql
   ALTER ROLE assetflow_<kind>_login WITH PASSWORD '<new_password>';
   ```

3. **Reload or Restart Services:**
   Restart the associated container service (`api`, `worker`, etc.) to pick up the updated secret from the mounted secret volume or vault lease.

In the minimal profile, steps 2 and 3 are one command: change the file, then run `make up-minimal`. The `db-roles` service re-applies every password from `.secrets/` on each start.

---

## 4. Applying the Standard to an Existing Database (minimal profile)

Roles and logins are applied by the one-shot `db-roles` service (`deploy/postgres/init-minimal.sh`) on every `make up-minimal`, before migrations run, not only when the database is first created. The script is idempotent:

- creates missing group roles and logins and re-applies their passwords;
- renames logins with the legacy names `assetflow_<kind>_user` to `assetflow_<kind>_login`, keeping their grants;
- if both the legacy and the new name exist, disables the legacy login (`NOLOGIN`) so only one credential per process kind can connect.

No manual step and no volume reset is needed when upgrading a development database.
