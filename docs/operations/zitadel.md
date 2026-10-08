<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# Zitadel operations runbook

**Audience:** developers (local identity) and operators of the full profile
**Master plan:** §B5.5, §B5.7, §B11.2, §B11.4, decisions 51 and 52 (setup plans P2-09 to P2-11, M1.6-T8)
**Files:** `scripts/bootstrap_zitadel.py`, `scripts/bootstrap.sh`, `scripts/bootstrap.ps1`, `setup.bat`,
`deploy/compose.identity.yml` (development), `deploy/compose.full.yml` (production),
`deploy/zitadel/{config,steps}.yaml`, `deploy/bootstrap/Dockerfile`, `config/organizations/*.yaml`

## 1. Overview

Zitadel is self-hosted (no Zitadel Cloud). One command sets it up and can be run again at any
time; the second run reports `No changes`:

| | Development (default) | Production (`ASSETFLOW_ENV=production`) |
| --- | --- | --- |
| Command | `scripts/bootstrap.sh` (Windows: `setup.bat`), or `make bootstrap` | `ASSETFLOW_ENV=production scripts/bootstrap.sh`, or `make up-full` |
| Compose file | `deploy/compose.identity.yml` (project `assetflow-dev`) | `deploy/compose.full.yml` (project `assetflow`) |
| Masterkey, passwords | generated once into `.env.local` (git-ignored) | generated once into OpenBao by `openbao-apply --generate-missing` |
| How Zitadel gets them | `${VAR}` interpolation from `.env.local` (`--masterkeyFromEnv`) | files rendered by OpenBao Agent into tmpfs (`--masterkeyFile`, second `--config`/`--steps`) |
| Bootstrap results | `.env.local` | OpenBao `secret/assetflow/idp` and `secret/assetflow/zitadel/*`, **never files** |
| Login policy | relaxed (marked `DEV ONLY` in the compose file) | strict: MFA forced, no self-registration, password change at first sign-in |

The flow follows OpenWind's setup, with three changes: no login-page scraping (the first
credential is the official first-instance machine user), organizations are automated from
config, and production secrets never touch a file.

```
generate secrets ──> zitadel start-from-init ──> bootstrap container ──> results
 (.env.local or         (init + setup +            (search first, create      (.env.local or
  OpenBao)               start, one service)        what is missing)           OpenBao)
```

## 2. Development: one command

Needs only Docker (Compose v2). From the repository root:

```bash
scripts/bootstrap.sh            # Linux, macOS, WSL2, Git Bash   (or: make bootstrap)
setup.bat                       # Windows (PowerShell 5.1+)
```

It runs four steps:

1. builds the bootstrap image (`deploy/bootstrap/Dockerfile`, python:3.12-slim + uv; the
   dependencies are pinned in the script's PEP 723 header);
2. `bootstrap_zitadel.py init-env`: creates `.env.local` values that are missing:
   `ZITADEL_MASTERKEY` (32 characters), `ZITADEL_ADMIN_PASSWORD` (32 characters, upper, lower,
   digit and symbol, never `$` or `%`), `ZITADEL_DB_PASSWORD`, `ZITADEL_DB_USER_PASSWORD`.
   Existing values are reused. It records a SHA-256 of the masterkey in the Zitadel bootstrap
   volume and stops if the volume was created with another masterkey (section 7);
3. starts Zitadel (`up --wait`: healthy on `/app/zitadel ready`); the first start takes about a minute;
4. runs the bootstrap (section 4) and prints the console URL and the admin login name.

The admin password is `ZITADEL_ADMIN_PASSWORD` in `.env.local`. Other commands:

```bash
scripts/bootstrap.sh --dry-run  # show what would change (setup.bat -DryRun)
make zitadel-apply              # bootstrap only (DRY_RUN=1 for a dry run)
make up-identity                # start again after make down-identity
make down-identity              # stop (data kept)
scripts/bootstrap.sh --reset    # delete the local Zitadel volumes and start over (setup.bat -Reset)
```

Containers of AssetFlow that need Zitadel join the Docker network `assetflow-dev` and call
`http://zitadel:8080` with the header `Host: localhost:19081` (the external domain and port), so
Zitadel finds its instance; the browser uses `http://localhost:19081`.

## 3. Runtime layout

Both profiles run **one** Zitadel service with `zitadel start-from-init` (init, setup of the first
instance and start; <https://zitadel.com/docs/self-hosting/deploy/compose>), pinned to
`ghcr.io/zitadel/zitadel:v4.19.3`, with its own PostgreSQL server (`zitadel-db`, never shared
with AssetFlow) and the login built into the API container (`LoginV2.Required: false`).

| Setting | Development | Production |
| --- | --- | --- |
| Masterkey | `--masterkeyFromEnv` (`ZITADEL_MASTERKEY`) | `--masterkeyFile /run/zitadel/masterkey` |
| TLS | `--tlsMode disabled`, `ZITADEL_TLS_ENABLED=false` | `--tlsMode ${ZITADEL_TLS_MODE:-external}`; `external` behind the TLS proxy |
| Health check | `/app/zitadel ready` | `/app/zitadel ready --config /zitadel/config.yaml` |

`zitadel ready` reads the configuration, not the `--tlsMode` flag: with the default
`TLS.Enabled: true` it probes https and reports `not ready` although Zitadel serves http. So TLS is
also disabled in configuration (`ZITADEL_TLS_ENABLED=false` in development, `TLS.Enabled: false` in
`config.yaml`), as in the upstream compose file.

A one-shot `zitadel-volume-init` container gives the bootstrap volume to the zitadel user
(uid 1000), so Zitadel itself runs as non-root and can write the first-instance key there.

**External URL.** `ZITADEL_DOMAIN`, `ZITADEL_EXTERNALPORT` and `ZITADEL_EXTERNALSECURE` must match the
public URL exactly, or Zitadel answers `Instance not found`:

| TLS mode | Public URL | Settings |
| --- | --- | --- |
| Local (no TLS) | `http://localhost:19081` | `localhost`, `19081`, `false` (defaults) |
| External TLS (nginx in front) | `https://id.example.com` | `id.example.com`, `443`, `true`, and `ZITADEL_TLS_MODE=external` |

`ExternalDomain` is fixed when the instance is created; changing it later needs the instance
domain to be added in Zitadel first.

## 4. The bootstrap (`scripts/bootstrap_zitadel.py`)

Runs in the bootstrap container (`make zitadel-apply`) against `http://zitadel:8080`, sending the
public `Host` header (and `X-Forwarded-Proto: https` when the public URL is https). It can also
run on a host with uv: `uv run scripts/bootstrap_zitadel.py [--dry-run]` with
`ZITADEL_BOOTSTRAP_URL=http://localhost:19081` (once the bootstrap key is stored). Each step
searches first, creates only what is missing, treats HTTP 409 as success and re-applies
settings with PUT only when they differ (Zitadel's `No changes` also counts as success):

1. wait for `/debug/ready`;
2. authenticate with the JWT profile grant: the stored bootstrap key, else the key that Zitadel
   wrote for the first-instance machine user `assetflow-bootstrap` (role `IAM_OWNER`,
   `FirstInstance.Org.Machine`, `FirstInstance.MachineKeyPath`; a PAT at
   `FirstInstance.PatPath` also works). That first key is **rotated at once**: a new key is
   stored, the old key is revoked in Zitadel and the file is deleted from the volume;
3. project `AssetFlow` in the platform organization `AssetFlow Platform`: assert roles on
   authentication, check roles on authentication, check for project on authentication;
4. project roles: `rbac.roles` from `config/assetflow.yaml` when that file exists, else the
   §B7.2 defaults `viewer`, `technician`, `team_lead`, `asset_manager`,
   `maintenance_planner`, `org_unit_manager`, `admin` (group `assetflow`). Roles that exist
   only in Zitadel are kept and listed;
5. `assetflow-web`: user-agent (public) client, authorization code with PKCE, auth method
   `NONE` (no secret), grants authorization code and refresh token, redirect
   `${APP_URL}/auth/callback`;
6. `assetflow-bff`: confidential web client (client secret basic), redirect
   `${API_URL}/api/v1/auth/callback`;
   both clients issue **JWT access tokens** with roles asserted in access and ID tokens; dev mode
   (http redirect URIs) only outside production;
7. `assetflow-introspection`: an **API application** with a client secret (basic) for
   `/oauth/v2/introspect`. Zitadel's introspection endpoint accepts API or OIDC applications of
   the project only; a machine user's client secret is refused there (`unauthorized_client`,
   observed on v4.19.3);
8. machine user `assetflow-automation` with instance role `IAM_ORG_MANAGER` and a JSON key, for
   runtime Management API calls (`assetflow org create --create-idp-org`, §B5.7);
9. one organization and project grant per `config/organizations/*.yaml` (section 5);
10. production only: login policy with MFA forced and self-registration off;
11. results are written (only when they differ) and printed without secret values.

A client secret or key is kept while the stored value still belongs to the object in Zitadel
(same client id, key id still listed, introspection secret still accepted); otherwise a new one
is generated. So a reset instance, a lost `.env.local` entry or a wrong value heals on the next run.

**Results.**

| `.env.local` (development) | OpenBao (production) |
| --- | --- |
| `ZITADEL_URL`, `ZITADEL_ISSUER` | `secret/assetflow/idp`: `url`, `issuer` |
| `ZITADEL_PROJECT_ID` (token audience) | `secret/assetflow/idp`: `project_id` |
| `ZITADEL_WEB_CLIENT_ID` | `secret/assetflow/idp`: `web_client_id` |
| `ZITADEL_BFF_CLIENT_ID`, `ZITADEL_BFF_CLIENT_SECRET` | `secret/assetflow/idp`: `client_id`, `client_secret` |
| `ZITADEL_INTROSPECTION_CLIENT_ID`, `..._SECRET` | `secret/assetflow/idp`: `introspection_client_id`, `introspection_client_secret` |
| `ZITADEL_SERVICE_ACCOUNT_KEY` (base64 JSON key) | `secret/assetflow/zitadel/automation-key`: `key_json` |
| `ZITADEL_BOOTSTRAP_KEY` (base64 JSON key) | `secret/assetflow/zitadel/bootstrap-key`: `key_json` |
| `ZITADEL_ORGANIZATIONS` (`slug:id,...`) | `secret/assetflow/zitadel/organizations`: `{slug: id}` |

In production the script refuses to write any file (the `.env.local` store raises an error), and
`init-env` refuses to run.

## 5. Multi-organization setup (§B5.5, decision 52)

- One Zitadel instance per AssetFlow installation; **one Zitadel organization per AssetFlow
  organization**. The platform organization owns the `AssetFlow` project.
- Each file `config/organizations/<slug>.yaml` declares one organization: `slug` (must equal
  the file name), `name`, and `idp.granted_roles` (the project roles that organization may
  assign; unknown roles stop the run). The bootstrap creates the Zitadel organization
  (v2 `POST /v2/organizations`, found again by name) and a project grant with those roles;
  when the roles in the file change, the grant is updated. Organization admins then assign
  roles to their users.
- Zitadel assigns the organization id. The bootstrap prints
  `organization <slug>: idp_organization_id <id>` and stores the map (table above);
  `assetflow org create --idp-org <id>` stores it in `organizations.idp_organization_id`.
- The samples `example-alpha` and `example-beta` use neutral names (no real companies).

**Sign-in request (Zitadel preset).** The AssetFlow sign-in page asks for the organization
(slug or email domain) and requests these scopes:

| Scope | Effect |
| --- | --- |
| `openid profile email` | standard claims |
| `urn:zitadel:iam:org:id:{id}` | only members of that organization can sign in |
| `urn:zitadel:iam:org:project:id:{projectId}:aud` | the project id is in the token audience |
| `urn:zitadel:iam:user:resourceowner` | adds `urn:zitadel:iam:user:resourceowner:id`, `:name`, `:primary_domain` |
| `urn:zitadel:iam:org:roles:id:{id}` | roles only from that organization |

**Token checks in AssetFlow.** The claim `urn:zitadel:iam:user:resourceowner:id` must equal the
`idp_organization_id` of the organization chosen on the sign-in page, and must match an
existing organization; otherwise sign-in stops with a toast message and nothing is created
(§B5.5). Roles come from `urn:zitadel:iam:org:project:roles` (asserted by the project) or
`urn:zitadel:iam:org:project:{projectId}:roles`; clients without an AssetFlow application
(for example machine users with client credentials) must add the scope
`urn:zitadel:iam:org:projects:roles` to get them.

Observed on a local stack (v4.19.3, fresh volumes, machine user of `example-alpha` with the
project role `technician` through the project grant, client credentials): the JWT access token
had the project id in `aud`, `urn:zitadel:iam:user:resourceowner:id` = alpha's id, the roles in
`urn:zitadel:iam:org:project:{projectId}:roles` (`{"technician": {"<alpha id>": ...}}`), its
signature verified against `/oauth/v2/keys`, and `assetflow-introspection` introspected it as
`active`. Earlier (P2-11) asking for `urn:zitadel:iam:org:id:{beta}` still returned a token, but
with alpha as resource owner, so the comparison above is what rejects an organization A token for
organization B. The interactive sign-in is covered by the Phase 1 sign-in tests (M1.3-T8).

## 6. Production

Prerequisites: OpenBao is unsealed, the operator token is in the shell, TLS files exist
(`docs/operations/openbao.md`). Then either `make up-full` (whole stack) or:

```bash
read -rs BAO_TOKEN && export BAO_TOKEN
ASSETFLOW_ENV=production scripts/bootstrap.sh     # openbao-apply, Zitadel, bootstrap into OpenBao
ASSETFLOW_ENV=production make zitadel-apply       # bootstrap only, after config changes
```

`openbao-apply --generate-missing` creates the masterkey, database passwords and the first-admin
password in OpenBao once (check-and-set: never overwritten). The bootstrap container receives
`BAO_TOKEN` from the operator's shell for that run only and reads the OpenBao CA from a compose
secret. The first admin is `admin` in `AssetFlow Platform` (login name printed by the bootstrap);
read the initial password once with
`bao kv get -field=initial_password secret/assetflow/zitadel/admin`; Zitadel asks for a new one at
first sign-in, and MFA setup is required.

The masterkey (`secret/assetflow/zitadel/masterkey`) is fixed at the first start and must never
change: back it up with the other key material (§B11.4).

## 7. Recovery

- **Masterkey changed or lost** (`init-env` stops with "created with a different masterkey", or
  Zitadel logs a decryption error): Zitadel encrypts its keys with the masterkey and cannot use
  another one. Restore the original value (development: the old `.env.local`; production:
  OpenBao backup). Development only: `scripts/bootstrap.sh --reset` deletes the local Zitadel
  volumes and starts a fresh instance with the secrets in `.env.local`.
- **Database password mismatch** (`password authentication failed`): same cause and remedy.
- **Bootstrap key lost** (not in the store, first-instance key already rotated): sign in to the
  console as the admin, open the machine user `assetflow-bootstrap`, create a JSON key and store
  it: development `ZITADEL_BOOTSTRAP_KEY=<base64 of the key file>` in `.env.local`; production
  `bao kv put secret/assetflow/zitadel/bootstrap-key key_json=@key.json`. Delete the file.
- **Rotate a secret**: delete the value from the store (for example `ZITADEL_BFF_CLIENT_SECRET`)
  and run the bootstrap; it generates a new one. For the automation key, delete the key in the
  console first.
- **Masterkey / volume consistency**: the bootstrap volume holds `.masterkey.sha256` (a hash,
  not the key); it is written on the first `init-env`.

## 8. Troubleshooting

- `Instance not found`: the Host / port / scheme of the request differs from
  `ZITADEL_DOMAIN` / `ZITADEL_EXTERNALPORT` / `ZITADEL_EXTERNALSECURE`. Containers calling
  `http://zitadel:8080` must send `Host: <domain>:<port>`.
- Container `unhealthy` while the log says `server is listening`: `zitadel ready` probes https;
  TLS must also be disabled in configuration (section 3).
- `no Zitadel credential`: see "Bootstrap key lost" above.
- Logs: `docker compose -f deploy/compose.identity.yml --env-file .env.local logs zitadel`.
