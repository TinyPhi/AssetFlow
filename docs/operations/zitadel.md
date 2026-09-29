<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# Zitadel operations runbook

**Audience:** operators of the full profile
**Master plan:** §B5.5, §B5.7, §B11.2, decisions 51 and 52 (setup plans P2-09 to P2-11)
**Files:** `deploy/zitadel/{config,steps}.yaml`, `deploy/zitadel/tofu/*.tf`,
`config/organizations/*.yaml`, `scripts/zitadel-apply.py`

## 1. Layout

Self-hosted only (no Zitadel Cloud), following the official prod-like compose layout
(<https://zitadel.com/docs/self-hosting/deploy/compose>) with separate steps:

| Service | Command | Purpose |
| --- | --- | --- |
| `zitadel-secrets` | OpenBao Agent | renders the masterkey, database passwords and first-admin password from OpenBao into a tmpfs volume |
| `zitadel-db` | PostgreSQL | Zitadel's own database server and users, never shared with AssetFlow |
| `zitadel-init` | `zitadel init` | creates the `zitadel` database and user |
| `zitadel-setup` | `zitadel setup` | runs migrations and creates the first instance (`steps.yaml`) |
| `zitadel` | `zitadel start` | serves the API, console and login; healthy on `zitadel ready` |

Credentials reach Zitadel only as files: `--masterkeyFile /run/zitadel/masterkey`, a second
`--config` file with the database passwords and a second `--steps` file with the first-admin
password, all rendered by the agent. `config.yaml` and `steps.yaml` hold no secrets.

**External URL.** `ZITADEL_DOMAIN`, `ZITADEL_EXTERNALPORT` and `ZITADEL_EXTERNALSECURE` are set
in the operator's shell (or a non-secret env file) and passed to Zitadel as
`ZITADEL_EXTERNALDOMAIN`, `ZITADEL_EXTERNALPORT`, `ZITADEL_EXTERNALSECURE`. They must match the
public URL exactly, or Zitadel answers `Instance not found`:

| TLS mode | Public URL | Settings |
| --- | --- | --- |
| Local (no TLS) | `http://localhost:8081` | `localhost`, `8081`, `false` (defaults) |
| External TLS (nginx in front) | `https://id.example.com` | `id.example.com`, `443`, `true` |

`ExternalDomain` is fixed when the instance is created; changing it later needs the
instance domain to be added in Zitadel first.

**Login.** The login built into the API container is used (`DefaultInstance.Features.LoginV2.Required: false`),
so no separate login container and no extra cookie secret are needed.

## 2. Start

Prerequisites: OpenBao is unsealed and `openbao-apply --generate-missing` has run
(`docs/operations/openbao.md`).

```bash
docker compose -f deploy/compose.full.yml up -d --wait zitadel
curl -fsS http://localhost:8081/debug/healthz          # ok
```

The console is at `http://localhost:8081/ui/console`. The first admin is `admin` in the
`AssetFlow Platform` organization; read the initial password once from
`secret/assetflow/zitadel/admin` (`bao kv get -field=initial_password secret/assetflow/zitadel/admin`);
Zitadel asks for a new one at first sign-in.

The masterkey (`secret/assetflow/zitadel/masterkey`) is fixed at the first start and must
never change: back it up with the other key material (§B11.4).

## 3. Zitadel as code (`make zitadel-apply`)

`scripts/zitadel-apply.py` runs OpenTofu (<https://opentofu.org>) with the official provider
(<https://registry.terraform.io/providers/zitadel/zitadel>) on `deploy/zitadel/tofu`:

- project `AssetFlow`, owned by the platform organization, with the §B7.2 roles
  (`viewer`, `technician`, `team_lead`, `asset_manager`, `maintenance_planner`,
  `org_unit_manager`, `admin`); "assert roles on authentication", "check authorization on
  authentication" and "check for project on authentication" are on;
- `assetflow-web`: public user-agent client, authorization code with PKCE, **no client secret**;
- `assetflow-bff`: confidential server client (client secret basic, refresh tokens);
- both clients issue **JWT access tokens** with roles asserted in access and ID tokens;
- machine user `assetflow-automation` (role `IAM_ORG_MANAGER`) and its JSON key, for
  `assetflow org create --create-idp-org` (§B5.7);
- one organization and one project grant per file in `config/organizations/` (section 4).

Flow of credentials:

1. Zitadel setup writes the key of the first-instance machine user `tofu-admin` (role
   `IAM_OWNER`) into the `zitadel_bootstrap` volume. The first `zitadel-apply` moves it into
   `secret/assetflow/zitadel/tofu-admin-key` and deletes it from the volume.
2. Each run writes that key to a temporary file (mode 0600) for OpenTofu and deletes it after.
3. After apply, the BFF client secret is written to `secret/assetflow/idp` and the automation
   key to `secret/assetflow/zitadel/automation-key`, only when they differ. Nothing is printed.

```bash
export BAO_ADDR=https://127.0.0.1:8200 BAO_CACERT=deploy/.secrets/openbao-tls/ca.pem
read -rs BAO_TOKEN && export BAO_TOKEN     # operator token
python scripts/zitadel-apply.py            # second run: "Zitadel: no changes."
python scripts/zitadel-apply.py --check    # offline: tofu init -backend=false + validate
```

OpenTofu state stays in `deploy/zitadel/tofu/terraform.tfstate` on the operator machine; it
contains the client secret and keys, is git-ignored and must be backed up like other key
material. Rotate the BFF secret or the automation key by tainting the resource
(`tofu apply -replace=...`) and re-running `zitadel-apply`.

If the `tofu-admin` key is lost (not in OpenBao and no longer in the volume), sign in to the
console as the admin, create a new JSON key for `tofu-admin`, and store it with
`bao kv put secret/assetflow/zitadel/tofu-admin-key key_json=@key.json`, then delete the file.

## 4. Multi-organization setup (§B5.5, decision 52)

- One Zitadel instance per AssetFlow installation; **one Zitadel organization per AssetFlow
  organization**. The platform organization owns the `AssetFlow` project.
- Each file `config/organizations/<slug>.yaml` declares one organization: `slug` (must equal
  the file name), `name`, and `idp.granted_roles` (the project roles that organization may
  assign; a subset of the project roles). `zitadel-apply` creates the Zitadel organization and
  a project grant with those roles. Organization admins then assign roles to their users.
- Zitadel assigns the organization id. `zitadel-apply` prints it per slug
  (`tofu output organization_ids`); `assetflow org create --idp-org <id>` stores it in
  `organizations.idp_organization_id`.
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

Observed on a local stack (P2-11 check, machine user of `example-alpha` with client
credentials): the token had the project id in `aud` and
`urn:zitadel:iam:user:resourceowner:id` = alpha's id. Asking for
`urn:zitadel:iam:org:id:{beta}` still returned a token, but without the
`urn:zitadel:iam:org:id` claim and with alpha as resource owner, so the comparison above is
what rejects an organization A token for organization B. The interactive sign-in (login page
restricted by the org scope) is covered by the Phase 1 sign-in tests (M1.3-T8).

## 5. Troubleshooting

- `Instance not found`: the Host / port / scheme of the request differs from
  `ZITADEL_DOMAIN` / `ZITADEL_EXTERNALPORT` / `ZITADEL_EXTERNALSECURE`.
- `zitadel-setup` fails with a masterkey error: the masterkey in OpenBao changed after the
  first start; restore the original value.
- `zitadel-apply` cannot authenticate: check that `tofu-admin` still exists and its key in
  OpenBao is valid (section 3).
