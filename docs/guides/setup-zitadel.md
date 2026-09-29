<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# Set up Zitadel for AssetFlow

This guide shows how I set up Zitadel as the sign-in provider for AssetFlow: a self-hosted Zitadel
instance, one idempotent bootstrap script that creates everything AssetFlow needs through Zitadel's
official APIs, and one Zitadel organization per AssetFlow organization. I followed the official Zitadel
documentation and took the overall pattern (one command, a containerized bootstrap that talks to the
Management API) from the OpenWind project.

Follow the same steps in your fork. The section [Customize for your installation](#customize-for-your-installation)
lists what you are expected to change.

> **Placeholders.** Every secret in this guide is written as `your-secret-1`, `your-secret-2`, and so on.
> Real values are generated on your machine and are never written into the repository.

## How it fits together

- One self-hosted Zitadel instance per AssetFlow installation. Its first organization,
  **AssetFlow Platform**, owns the `AssetFlow` project.
- **One Zitadel organization per AssetFlow organization.** Each is declared in
  `config/organizations/<slug>.yaml` and receives a **project grant** listing the roles it may use.
- AssetFlow finds the organization of a signed-in user from the token claim
  `urn:zitadel:iam:user:resourceowner:id` (master plan §B5.5, decision 52).
- Development keeps the generated values in `.env.local` (git-ignored). Production keeps them only in
  OpenBao ([Set up OpenBao](setup-openbao.md)).

## Prerequisites

| Environment | You need |
| --- | --- |
| Development | Docker with Compose v2. Nothing else: the bootstrap runs in its own container. |
| Production | The above, plus an initialized and unsealed OpenBao and an operator token ([Set up OpenBao](setup-openbao.md)) |

## Files

| File | Purpose |
| --- | --- |
| `deploy/compose.identity.yml` | development stack: PostgreSQL for Zitadel, Zitadel, the bootstrap container |
| `deploy/compose.full.yml` | production stack (Zitadel reads its secrets from OpenBao) |
| `deploy/zitadel/config.yaml`, `deploy/zitadel/steps.yaml` | production Zitadel configuration and first-instance steps |
| `deploy/bootstrap/Dockerfile` | image for the bootstrap (Python 3.12 + uv) |
| `scripts/bootstrap_zitadel.py` | the idempotent bootstrap |
| `scripts/bootstrap.sh`, `scripts/bootstrap.ps1`, `setup.bat` | one-command setup (Linux/macOS/Git Bash, PowerShell, Windows) |
| `config/organizations/*.yaml` | one file per AssetFlow organization |
| `.env.example` | the names used in `.env.local` (no values) |

## Step 1: Run the setup

I ran one command from the repository root:

```bash
scripts/bootstrap.sh          # Linux, macOS, Git Bash
```

```bat
setup.bat                     & rem Windows (runs scripts\bootstrap.ps1)
```

`make bootstrap` runs the same script. It performs four steps:

1. **Builds the bootstrap image** from `deploy/bootstrap/Dockerfile`.
2. **Creates the local secrets** in `.env.local` when they are missing: a 32-character masterkey, the
   first admin's password and two database passwords. Existing values are reused. It also records a
   fingerprint of the masterkey in the Zitadel volume and stops with an explanation if the volume was
   created with a different masterkey.
3. **Starts Zitadel** (`ghcr.io/zitadel/zitadel:v4.19.3`) with its own PostgreSQL (`postgres:16-alpine`)
   and waits until the health check `/app/zitadel ready` passes. The first start takes about a minute.
4. **Runs the bootstrap** (`scripts/bootstrap_zitadel.py apply`) in its container.

After the first run, `.env.local` contains values like these (placeholders shown):

```dotenv
ZITADEL_MASTERKEY=your-secret-1
ZITADEL_ADMIN_PASSWORD=your-secret-2
ZITADEL_DB_PASSWORD=your-secret-3
ZITADEL_DB_USER_PASSWORD=your-secret-4
ZITADEL_URL=http://localhost:8081
ZITADEL_ISSUER=http://localhost:8081
ZITADEL_PROJECT_ID=your-project-id
ZITADEL_WEB_CLIENT_ID=your-web-client-id
ZITADEL_BFF_CLIENT_ID=your-bff-client-id
ZITADEL_BFF_CLIENT_SECRET=your-secret-5
ZITADEL_INTROSPECTION_CLIENT_ID=your-introspection-client-id
ZITADEL_INTROSPECTION_CLIENT_SECRET=your-secret-6
ZITADEL_SERVICE_ACCOUNT_KEY=your-secret-7
ZITADEL_BOOTSTRAP_KEY=your-secret-8
ZITADEL_ORGANIZATIONS=example-alpha:your-org-id-a,example-beta:your-org-id-b
```

> **Never change `ZITADEL_MASTERKEY` after the first start.** Zitadel encrypts its data with it.
> The only way to change it in development is to start over (Step 5).

## Step 2: Understand how the first credential is created

Zitadel creates a machine user on its first start (the official first-instance settings), so no
password has to be typed and no login page is automated:

```yaml
ZITADEL_FIRSTINSTANCE_ORG_MACHINE_MACHINE_USERNAME: assetflow-bootstrap
ZITADEL_FIRSTINSTANCE_ORG_MACHINE_MACHINEKEY_TYPE: "1"            # JSON key
ZITADEL_FIRSTINSTANCE_MACHINEKEYPATH: /zitadel/bootstrap/bootstrap-key.json
```

Zitadel writes the key once into the `zitadel_bootstrap` volume. The bootstrap signs in with it
(JWT profile grant), then **rotates it**: it stores a new key (`ZITADEL_BOOTSTRAP_KEY`), revokes the
old key in Zitadel and deletes the file. Later runs sign in with the stored key.

## Step 3: What the bootstrap creates

Every step searches first and creates only what is missing. "Already exists" (HTTP 409) counts as
success, and settings are re-applied only when they differ. On my first run it printed
`==> Applied 19 change(s).`; the second run printed `==> No changes.`

| Order | What | Settings |
| --- | --- | --- |
| 1 | wait for Zitadel | `/debug/ready` |
| 2 | sign in | stored bootstrap key, else the first-instance key (then rotated) |
| 3 | project `AssetFlow` | in the platform organization; role assertion, role check, project check on |
| 4 | project roles | `rbac.roles` from `config/assetflow.yaml` if present, else the defaults below |
| 5 | app `assetflow-web` | public user-agent client, authorization code + PKCE, no secret, JWT access tokens, roles in access and ID tokens, refresh tokens |
| 6 | app `assetflow-bff` | confidential web client (client secret basic, refresh tokens); secret → `ZITADEL_BFF_CLIENT_SECRET` |
| 7 | app `assetflow-introspection` | API application with a client secret, for token introspection |
| 8 | machine user `assetflow-automation` | role `IAM_ORG_MANAGER`, JSON key → `ZITADEL_SERVICE_ACCOUNT_KEY` (runtime Management API calls) |
| 9 | organizations | one per `config/organizations/*.yaml`, each with a project grant of its `idp.granted_roles` |
| 10 | login policy | production only: MFA forced, self-registration off |
| 11 | results | written to `.env.local` (development) or OpenBao (production); secret values are never printed |

Default roles: `viewer`, `technician`, `team_lead`, `asset_manager`, `maintenance_planner`,
`org_unit_manager`, `admin`.

A note from my live test: an introspection **machine user** with a client secret was rejected by
`/oauth/v2/introspect` (`400 unauthorized_client`), so the bootstrap uses an **API application**,
which returned `200 {"active": true}`.

## Step 4: Sign in to the console

The summary prints the console URL. With the defaults:

- Console: `http://localhost:8081/ui/console`
- User: `admin` (the value of `ZITADEL_ADMIN_USERNAME`, default `admin`)
- Password: `ZITADEL_ADMIN_PASSWORD` in `.env.local` (`your-secret-2`)

In development the admin is not asked to change the password, MFA is not forced and the v2 login
UI is not required (`ZITADEL_DEFAULTINSTANCE_*` settings in `deploy/compose.identity.yml`). These
relaxations exist only in the development file.

## Step 5: Run it again, preview or start over

| Goal | Command |
| --- | --- |
| Re-apply (safe any time) | `scripts/bootstrap.sh` |
| Show planned changes only | `scripts/bootstrap.sh --dry-run` (PowerShell: `-DryRun`) |
| Start over in development | `scripts/bootstrap.sh --reset` (PowerShell: `-Reset`); deletes the local Zitadel containers and volumes, keeps `.env.local` |
| Re-apply without the full setup | `make zitadel-apply` (`DRY_RUN=1` to preview) |
| Start / stop the local Zitadel | `make up-identity` / `make down-identity` (data kept) |

## Step 6: Add an organization

1. Copy `config/organizations/example-alpha.yaml` to `config/organizations/<your-slug>.yaml`. The slug
   must equal the file name.
2. Set `name`, and list in `idp.granted_roles` the roles this organization may assign (a subset of the
   project roles).
3. Run `scripts/bootstrap.sh` (or `make zitadel-apply`).

The bootstrap creates the Zitadel organization and its project grant, prints the Zitadel organization id,
and adds it to `ZITADEL_ORGANIZATIONS` (development) or `secret/assetflow/zitadel/organizations`
(production). That id is the organization's `idp_organization_id` in AssetFlow.

```yaml
slug: your-slug
name: Your Organization
idp:
  provider: zitadel
  granted_roles:
    - viewer
    - technician
    - admin
```

## Step 7: Sign-in scopes and token claims

The AssetFlow sign-in request asks for these scopes (master plan §B5.5):

| Scope | Effect |
| --- | --- |
| `openid profile email` | standard OIDC |
| `urn:zitadel:iam:org:id:{id}` | only members of that organization may sign in |
| `urn:zitadel:iam:org:project:id:{projectId}:aud` | the project id is added to the access token audience |
| `urn:zitadel:iam:user:resourceowner` | the user's organization id, name and primary domain are added to the token |
| `urn:zitadel:iam:org:roles:id:{id}` | roles are limited to that organization |

AssetFlow then checks:

- the signature against Zitadel's JWKS, the issuer and the audience (the project id);
- `urn:zitadel:iam:user:resourceowner:id` against `organizations.idp_organization_id`; an unknown
  organization is rejected and nothing is created.

What I verified live with a test user of organization A: the audience contained the project id, the
`resourceowner:id` claim equalled organization A's id, and the signature verified against the JWKS.

> **Always check `resourceowner:id` in AssetFlow.** In my test, the `urn:zitadel:iam:org:id:{id}` scope
> was **not** enforced for a machine client using client credentials: a token requested with
> organization B's scope still belonged to organization A. The claim check is what keeps organizations apart.

For client-credentials tokens, the roles are in `urn:zitadel:iam:org:project:{projectId}:roles`.

## Step 8: Production

In production the same script runs with `ASSETFLOW_ENV=production` and an operator token:

```bash
export ASSETFLOW_ENV=production
read -rs BAO_TOKEN && export BAO_TOKEN     # paste the operator token (your-secret-9)
scripts/bootstrap.sh
```

It then:

1. starts OpenBao and stops if it is sealed;
2. runs `openbao-apply` with `--generate-missing --issue-secret-ids`, which creates the masterkey and
   the Zitadel passwords in OpenBao once;
3. starts Zitadel from `deploy/compose.full.yml`. Zitadel reads its masterkey from a file
   (`--masterkeyFile`) that an OpenBao Agent renders into an in-memory volume, so no credential is placed
   in the container environment;
4. runs the bootstrap, which writes its results only to OpenBao:

| OpenBao path | Contents |
| --- | --- |
| `secret/assetflow/idp` | `url`, `issuer`, `project_id`, `web_client_id`, `client_id`, `client_secret`, `introspection_client_id`, `introspection_client_secret` |
| `secret/assetflow/zitadel/bootstrap-key` | `key_json` (bootstrap machine user) |
| `secret/assetflow/zitadel/automation-key` | `key_json` (`assetflow-automation`) |
| `secret/assetflow/zitadel/organizations` | organization slug → Zitadel organization id |

The bootstrap refuses to write files in production. `--reset` is refused in production.
The first admin's password is in OpenBao: `bao kv get -field=initial_password secret/assetflow/zitadel/admin`.
`make up-full` runs the same order as part of the full stack.

The production path depends on an unsealed OpenBao; I verified it with the unit tests (a fake OpenBao)
and the compose validation, and the development path live.

## Verify

| Check | Command | Expected |
| --- | --- | --- |
| Zitadel healthy | `docker compose -f deploy/compose.identity.yml ps zitadel` | `healthy` |
| Idempotent | `scripts/bootstrap.sh` (second run) | `==> No changes.` |
| Nothing planned | `scripts/bootstrap.sh --dry-run` | `0 planned change(s)` |
| Unit tests | `make test-scripts` | `12 passed` |
| Console | open `http://localhost:8081/ui/console` | sign-in page |

## Customize for your installation

| What | Where | Notes |
| --- | --- | --- |
| Public domain and port | `ZITADEL_DOMAIN`, `ZITADEL_EXTERNALPORT`, `ZITADEL_EXTERNALSECURE` | must match the public URL exactly, or Zitadel answers "Instance not found"; they are fixed at the first start |
| App URLs (redirect URIs) | `APP_URL`, `API_URL` | set them to your frontend and API URLs |
| Roles | `rbac.roles` in `config/assetflow.yaml` | otherwise the defaults in Step 3 |
| Organizations | `config/organizations/*.yaml` | one file per organization (Step 6) |
| First organization and admin | `ZITADEL_FIRSTINSTANCE_ORG_*` in the compose files | set before the first start |
| Login strictness | `ZITADEL_DEFAULTINSTANCE_LOGINPOLICY_*` (development), `deploy/zitadel/config.yaml` (production) | keep MFA forced and self-registration off in production |
| Zitadel version | image tag in the compose files | upgrade one version at a time and read the release notes |
| TLS | `--tlsMode` | development uses `disabled`; in production terminate TLS at a reverse proxy and set `ZITADEL_EXTERNALSECURE=true` before the first start |

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| Zitadel stays unhealthy although it logs `server is listening` | `zitadel ready` probes HTTPS by default | keep `ZITADEL_TLS_ENABLED: "false"` when `--tlsMode disabled` |
| `cannot decrypt` / `message authentication failed` at start | masterkey differs from the one the volume was created with | restore the original value, or in development `scripts/bootstrap.sh --reset` |
| `password authentication failed` at start | database passwords differ from the volume's | restore them, or in development `--reset` |
| `Instance not found` | request Host differs from `ZITADEL_DOMAIN:ZITADEL_EXTERNALPORT` | use the configured domain and port; the bootstrap sends this Host header itself |
| Bootstrap cannot sign in | stored key revoked or volume recreated | development: `--reset`; production: restore `secret/assetflow/zitadel/bootstrap-key` |
| Sign-in rejected for an organization | organization id not known to AssetFlow | check `ZITADEL_ORGANIZATIONS` and the organization's `idp_organization_id` |

## References

- Self-hosting with Docker Compose: https://zitadel.com/docs/self-hosting/deploy/compose
- Configuration and first-instance settings: https://zitadel.com/docs/self-hosting/manage/configure
- TLS modes: https://zitadel.com/docs/self-hosting/manage/tls_modes
- Production checklist: https://zitadel.com/docs/guides/manage/production-checklist
- Reserved scopes: https://zitadel.com/docs/apis/openidoauth/scopes
- Pattern reference: OpenWind (`scripts/bootstrap.ts`, `setup.sh`), https://github.com/TinyPhi/OpenWind
- Operator runbook in this repository: [docs/operations/zitadel.md](../operations/zitadel.md)
