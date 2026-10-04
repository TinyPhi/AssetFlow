<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# OpenBao operations and unseal runbook

**Audience:** operators of the full profile
**Master plan:** §B11.4, §C5.5, decision 51 (setup plans P2-07, P2-08)
**Files:** `deploy/openbao/config/openbao.hcl`, `deploy/openbao/policies/*.hcl`,
`deploy/openbao/operator/*.hcl`, `deploy/openbao/agent/*.hcl`, `scripts/openbao-apply.py`

## 1. Rules

- OpenBao runs in production (server) mode with Raft storage and a TLS listener in every
  install. The `-dev` server is never used outside a developer's own throwaway container.
- Unseal key shares, the root token and every credential stay out of the repository, out of
  compose files, `.env` files, environment variables and images (decision 51).
- Applications read secrets at boot with their own AppRole; the role id and secret id are
  mounted as read-only files. Nothing else is handed to a container.
- The root token is used once, for the first `openbao-apply`, and is then revoked.

References: [configuration](https://openbao.org/docs/configuration/),
[seal](https://openbao.org/docs/configuration/seal/), [KV v2](https://openbao.org/docs/secrets/kv/kv-v2/),
[transit](https://openbao.org/docs/secrets/transit/), [AppRole](https://openbao.org/docs/auth/approle/),
[policies](https://openbao.org/docs/concepts/policies/), [Agent](https://openbao.org/docs/agent-and-proxy/agent/).

## 2. TLS certificate

The listener needs a certificate valid for `openbao` (the compose service name) and, for
operators on the host, `localhost` / `127.0.0.1`. Files live in `deploy/.secrets/openbao-tls/`
(git-ignored) and compose mounts them as secrets:

| File | Used by |
| --- | --- |
| `ca.pem` | every client (`BAO_CACERT`) |
| `server.pem` | OpenBao listener (`tls_cert_file`) |
| `server-key.pem` | OpenBao listener (`tls_key_file`) |

- Development and evaluation: `sh deploy/openbao/gen-dev-tls.sh` creates a local CA and a
  server certificate (the CA key is discarded).
- Production: put a certificate from your CA at the same paths. The files must be readable
  by the container user (uid 100); keep the directory itself `0700`.

## 3. First start, init and unseal

```bash
docker compose -f deploy/compose.full.yml up -d openbao
docker compose -f deploy/compose.full.yml exec openbao bao status   # Initialized false, Sealed true (exit code 2)
```

Initialize once, with the output going only to the key holders' terminals (never to a file
in the repository or a shared disk):

```bash
docker compose -f deploy/compose.full.yml exec openbao bao operator init -key-shares=5 -key-threshold=3
```

- Give each of the 5 unseal key shares to a different named key holder (§B11.4: the
  operator names the holders; for TinyPhi installs the TinyPhi owners, §D11 Q9).
- Keep the initial root token only until step 4 below.

Unseal after every start or restart (3 of 5 holders, each on their own terminal):

```bash
docker compose -f deploy/compose.full.yml exec openbao bao operator unseal   # prompts for one key share
docker compose -f deploy/compose.full.yml exec openbao bao status             # Sealed false (exit code 0)
```

The `openbao` health check runs `bao status`, which exits 0 only when OpenBao is initialized
and unsealed, so no dependent container starts while it is sealed.

**Auto-unseal (optional).** Instead of Shamir shares, a `seal` stanza (transit, or a cloud KMS)
can be added to `openbao.hcl` following <https://openbao.org/docs/configuration/seal/>. Any
credential that seal needs is supplied through the mechanism that page describes for your
seal type, never written into `openbao.hcl` or the repository.

## 4. Apply the configuration (engines, policies, AppRole)

From the repository root, in the operator's shell:

```bash
export BAO_ADDR=https://127.0.0.1:19200
export BAO_CACERT=deploy/.secrets/openbao-tls/ca.pem
read -rs BAO_TOKEN && export BAO_TOKEN          # root token on the first run only
python scripts/openbao-apply.py --generate-missing
```

It applies, only where something differs (a second run prints `No changes.`):

- KV v2 at `secret/`; transit at `transit/` with key `assetflow-fields`
  (aes256-gcm96, `exportable=false`, deletion not allowed, auto-rotated every 8760h; old
  versions stay for decryption);
- the ACL policies from `deploy/openbao/policies/` (one AppRole each) and
  `deploy/openbao/operator/assetflow-operator.hcl` (for people, no AppRole);
- one AppRole per service policy: periodic tokens (1h period, renewed by the service),
  secret ids valid 24h, secret ids and tokens bound to the compose network
  (`ASSETFLOW_NET_CIDR`, default `172.28.0.0/24`);
- `deploy/.secrets/<role>/role_id` and `secret_id` (git-ignored), mounted read-only by compose.
  A still-valid secret id is kept; `--issue-secret-ids` issues fresh ones (use it in the
  start procedure, see `docs/operations/startup.md`).
- with `--generate-missing`: random values for the Zitadel masterkey, the Zitadel database
  passwords, the Zitadel first-admin password and the PostgreSQL superuser password, written
  only when the path does not exist yet (check-and-set). Values are never printed.

Then replace the root token with an operator token and revoke the root token:

```bash
bao token create -policy=assetflow-operator -orphan -ttl=8h   # give this token to the operator
bao token revoke -self                                         # run with the root token
```

Later runs use the operator token. If a root token is ever needed again (for example to
change the operator policy), generate one with `bao operator generate-root` and the key
holders, use it, and revoke it.

## 5. Policies and secret layout

| Role (policy) | May read | Transit `assetflow-fields` |
| --- | --- | --- |
| `assetflow-api` | `secret/assetflow/{database,idp,smtp}` (plus write-only `secret/assetflow/orgs/+/channels/*`, below) | encrypt, decrypt |
| `assetflow-worker` | `secret/assetflow/{database,smtp}`, `secret/assetflow/orgs/*` | encrypt, decrypt |
| `assetflow-migrator` | `secret/assetflow/{migrator,database}` | none |
| `assetflow-postgres` | `secret/assetflow/postgres` | none |
| `zitadel` | `secret/assetflow/zitadel/{masterkey,database,admin}` | none |

All application policies are read-only except one path: the api role may `create`, `update`, `patch` and `delete`
(never `read` or `list`) `secret/assetflow/orgs/+/channels/*`, so an admin can save or remove a channel
credential but nothing can read one back; only the worker's channel runtime reads it. `secret/assetflow/migrator` is explicitly denied to
the api and worker. Secret layout (KV v2 under `secret/`):

| Path | Keys | Written by |
| --- | --- | --- |
| `assetflow/database` | runtime database role credentials | operator / bootstrap |
| `assetflow/migrator` | migration role credentials | operator / bootstrap |
| `assetflow/postgres` | `superuser_password` | `openbao-apply --generate-missing` |
| `assetflow/smtp` | SMTP relay credentials | operator |
| `assetflow/idp` | `url`, `issuer`, `project_id`, `web_client_id`, `client_id`, `client_secret`, `introspection_client_id`, `introspection_client_secret` | Zitadel bootstrap (`make zitadel-apply`) |
| `assetflow/orgs/<organization_id>/channels/<channel_id>` | channel credentials | api (write-only); read by the worker's channel runtime (§B6.3) |
| `assetflow/zitadel/masterkey` | `value` (32 characters, never changes) | `openbao-apply --generate-missing` |
| `assetflow/zitadel/database` | `admin_password`, `user_password` | `openbao-apply --generate-missing` |
| `assetflow/zitadel/admin` | `initial_password` (change on first sign-in) | `openbao-apply --generate-missing` |
| `assetflow/zitadel/bootstrap-key` | `key_json` | Zitadel bootstrap (rotated from the first-instance key) |
| `assetflow/zitadel/automation-key` | `key_json` | Zitadel bootstrap |
| `assetflow/zitadel/organizations` | `{slug: Zitadel organization id}` | Zitadel bootstrap |

Check a policy with a short-lived token, for example that the api cannot read the migrator
credentials:

```bash
T=$(bao token create -policy=assetflow-api -ttl=5m -field=token)
bao token capabilities "$T" secret/data/assetflow/migrator   # deny
bao token capabilities "$T" secret/data/assetflow/database   # read
```

## 6. How containers get secrets

- `api` (and later `worker`, `migrator`) log in with AppRole using `BAO_ROLE_ID_FILE` and
  `BAO_SECRET_ID_FILE` (paths under `/run/secrets`) and read their secrets into memory.
- Images that cannot talk to OpenBao (PostgreSQL, Zitadel) get their values from an OpenBao
  Agent sidecar (`postgres-secrets`, `zitadel-secrets`) that logs in with its own AppRole and
  renders files into an in-memory (tmpfs) volume, mounted read-only into the consumer. The
  agent keeps running so the volume stays mounted and rotated values are re-rendered.

## 7. Health and troubleshooting

`GET /v1/sys/health`: 200 active and unsealed, 429 standby, 501 not initialized, 503 sealed.

- AssetFlow boot stops with `platform.secrets_unavailable` when OpenBao is sealed or
  unreachable (§B11.4); unseal (section 3) and restart the service.
- An agent keeps restarting: check `docker compose -f deploy/compose.full.yml logs zitadel-secrets`;
  usually OpenBao is sealed, or the secret id expired (run `openbao-apply --issue-secret-ids`).
- `permission denied` on login from a container: the container address is outside
  `ASSETFLOW_NET_CIDR`; keep the compose network and the setting in step.
