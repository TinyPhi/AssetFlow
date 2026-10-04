<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# Set up OpenBao for AssetFlow

This guide shows how I set up OpenBao as the secrets store for AssetFlow: a production-mode
server with Raft storage and TLS, the policies and AppRole logins for each service, and the way
containers receive their secrets at start. I followed the official OpenBao documentation for every
step and link to the page I used.

Follow the same steps in your fork. The section [Customize for your installation](#customize-for-your-installation)
lists what you are expected to change.

> **Placeholders.** Every secret in this guide is written as `your-secret-1`, `your-secret-2`, and so on.
> Real values are generated on your machine and are never written into the repository.

## How it fits together

- OpenBao holds every server-side credential in production (master plan §B11.4, decision 51).
- Each service (api, worker, migrator, PostgreSQL, Zitadel) has its own policy and its own AppRole login.
- A container receives only two files: its AppRole `role_id` and `secret_id`. It reads its secrets
  into memory at start. No credential goes into environment variables, `.env` files or images.
- Images that cannot talk to OpenBao themselves (PostgreSQL, Zitadel) get their values from an
  OpenBao Agent sidecar that renders files into an in-memory volume.

Start order: OpenBao → unseal → apply configuration → Zitadel → AssetFlow.

## Prerequisites

| Tool | Why |
| --- | --- |
| Docker with Compose v2 | runs OpenBao (`openbao/openbao:2.6.3`) and the agents |
| Python 3.12 | runs `scripts/openbao-apply.py` (standard library only) |
| OpenSSL | creates the local development certificate |
| A shell | Bash on Linux and macOS; Git Bash on Windows |
| OpenBao CLI `bao` (optional on the host) | Steps 6 and 7; without it, run the same commands inside the container (see Step 6) |

All commands run from the repository root.

## Files

| File | Purpose |
| --- | --- |
| `deploy/openbao/config/openbao.hcl` | server configuration: Raft storage, TLS listener, addresses, lease TTLs |
| `deploy/openbao/policies/*.hcl` | one ACL policy per service; each gets an AppRole |
| `deploy/openbao/operator/assetflow-operator.hcl` | policy for people who operate OpenBao (no AppRole) |
| `deploy/openbao/agent/*.hcl` | OpenBao Agent configs for PostgreSQL and Zitadel |
| `deploy/openbao/gen-dev-tls.sh` | creates a local CA and server certificate for development |
| `scripts/openbao-apply.py` | applies engines, policies and AppRoles idempotently |
| `deploy/.secrets/` | generated TLS files and AppRole files (git-ignored, never committed) |

## Step 1: Review the server configuration

`deploy/openbao/config/openbao.hcl` runs OpenBao in production mode. I did not use the `-dev` server
anywhere except throwaway local tests, because dev mode keeps data in memory and starts unsealed with
a known root token.

```hcl
ui            = false
disable_mlock = true   # recommended with Raft storage

storage "raft" {
  path    = "/openbao/file"
  node_id = "assetflow-openbao-1"
}

listener "tcp" {
  address         = "0.0.0.0:8200"
  cluster_address = "0.0.0.0:8201"
  tls_disable     = false
  tls_cert_file   = "/run/secrets/openbao_tls_cert"
  tls_key_file    = "/run/secrets/openbao_tls_key"
  tls_min_version = "tls12"
}

api_addr          = "https://openbao:8200"
cluster_addr      = "https://openbao:8201"
default_lease_ttl = "1h"
max_lease_ttl     = "768h"
```

References: [Configuration](https://openbao.org/docs/configuration/),
[Raft storage](https://openbao.org/docs/configuration/storage/raft/),
[TCP listener](https://openbao.org/docs/configuration/listener/tcp/).

## Step 2: Create the TLS certificate

The listener needs a certificate valid for `openbao` (the compose service name) and for
`localhost` / `127.0.0.1` (operators on the host).

For development I generated one with the included script:

```bash
sh deploy/openbao/gen-dev-tls.sh
```

It writes three files to `deploy/.secrets/openbao-tls/` (directory mode `0700`) and discards the CA key:

| File | Used by |
| --- | --- |
| `ca.pem` | every client (`BAO_CACERT`) |
| `server.pem` | the listener (`tls_cert_file`) |
| `server-key.pem` | the listener (`tls_key_file`) |

Running it again does nothing if the files exist; `--force` replaces them. The certificate is valid for
825 days by default (`OPENBAO_TLS_DAYS`).

For production, I put a certificate from my own CA at the same three paths. The files must be readable
by the container user (uid 100).

## Step 3: Start OpenBao

```bash
docker compose -f deploy/compose.full.yml up -d openbao
docker compose -f deploy/compose.full.yml exec openbao bao status
```

On the first start the status shows `Initialized false` and `Sealed true`, and the command exits with code 2.
The container health check runs `bao status`, so it stays unhealthy, and no dependent container starts,
until OpenBao is initialized and unsealed.

## Step 4: Initialize and unseal

I initialized OpenBao once, with 5 key shares and a threshold of 3:

```bash
docker compose -f deploy/compose.full.yml exec openbao bao operator init -key-shares=5 -key-threshold=3
```

The output looks like this (values replaced):

```text
Unseal Key 1: your-secret-1
Unseal Key 2: your-secret-2
Unseal Key 3: your-secret-3
Unseal Key 4: your-secret-4
Unseal Key 5: your-secret-5

Initial Root Token: your-secret-6
```

What I did with these values:

- gave each unseal key share to a different named key holder, and stored none of them in OpenBao,
  in the repository or on the same machine as the database backups;
- kept the root token only until Step 6.

Then I unsealed with three of the five shares. The command prompts for one share each time:

```bash
docker compose -f deploy/compose.full.yml exec openbao bao operator unseal
docker compose -f deploy/compose.full.yml exec openbao bao operator unseal
docker compose -f deploy/compose.full.yml exec openbao bao operator unseal
docker compose -f deploy/compose.full.yml exec openbao bao status   # Sealed false, exit code 0
```

OpenBao seals itself again on every restart, so the unseal step repeats after each restart.
If you prefer not to unseal by hand, configure auto-unseal with a `seal` stanza
([Seal configuration](https://openbao.org/docs/configuration/seal/)).

## Step 5: Apply engines, policies and AppRoles

In my own shell on the host (never inside a container):

```bash
export BAO_ADDR=https://127.0.0.1:8200
export BAO_CACERT=deploy/.secrets/openbao-tls/ca.pem
read -rs BAO_TOKEN && export BAO_TOKEN     # paste your-secret-6 (root token), first run only
python scripts/openbao-apply.py --generate-missing
```

The script talks to the OpenBao HTTP API and changes something only when it differs. It:

1. mounts KV v2 at `secret/` and the transit engine at `transit/`;
2. creates the transit key `assetflow-fields` (`aes256-gcm96`, not exportable, deletion not allowed,
   rotated every 8760 hours; old versions stay available for decryption);
3. writes every policy from `deploy/openbao/policies/` and `deploy/openbao/operator/`;
4. creates one AppRole per service policy: periodic tokens with a 1-hour period, secret ids valid
   24 hours, secret ids and tokens bound to the compose network (`ASSETFLOW_NET_CIDR`, default
   `172.28.0.0/24`);
5. writes `deploy/.secrets/<role>/role_id` and `secret_id`, which compose mounts read-only;
6. with `--generate-missing`, creates random values for the Zitadel masterkey, the Zitadel database
   passwords, the Zitadel first-admin password and the PostgreSQL superuser password, only where the
   path does not exist yet (check-and-set, so existing values are never overwritten).

It never prints a secret value. When I ran it a second time, it printed `No changes.`

References: [AppRole](https://openbao.org/docs/auth/approle/),
[KV v2](https://openbao.org/docs/secrets/kv/kv-v2/),
[Transit](https://openbao.org/docs/secrets/transit/),
[Policies](https://openbao.org/docs/concepts/policies/).

## Step 6: Replace the root token

I created an operator token, then revoked the root token:

```bash
bao token create -policy=assetflow-operator -orphan -ttl=8h   # prints your-secret-7 (operator token)
bao token revoke -self                                         # run while BAO_TOKEN is still the root token
```

Without the `bao` CLI on the host, I run the same commands inside the container, which already has `BAO_ADDR` and `BAO_CACERT` set:

```bash
docker compose -f deploy/compose.full.yml exec -e BAO_TOKEN openbao bao token create -policy=assetflow-operator -orphan -ttl=8h
```

Later runs of `openbao-apply.py` use the operator token (`your-secret-7`). If I ever need a root token
again, I generate a new one with `bao operator generate-root` together with the key holders, use it and
revoke it.

## Step 7: Check what each service can read

| Role (policy) | May read | Transit `assetflow-fields` |
| --- | --- | --- |
| `assetflow-api` | `secret/assetflow/{database,idp,smtp}` (plus write-only `secret/assetflow/orgs/+/channels/*`, below) | encrypt, decrypt |
| `assetflow-worker` | `secret/assetflow/{database,smtp}`, `secret/assetflow/orgs/*` | encrypt, decrypt |
| `assetflow-migrator` | `secret/assetflow/{migrator,database}` | none |
| `assetflow-postgres` | `secret/assetflow/postgres` | none |
| `zitadel` | `secret/assetflow/zitadel/{masterkey,database,admin}` | none |

All application policies are read-only except one path: the api may write (create, update, patch, delete), but never read or list,
`secret/assetflow/orgs/+/channels/*` (channel credentials are write-only from the admin form; only the
worker's channel runtime reads them). `secret/assetflow/migrator` is explicitly denied to the api
and the worker. I checked this with a short-lived token:

```bash
T=$(bao token create -policy=assetflow-api -ttl=5m -field=token)
bao token capabilities "$T" secret/data/assetflow/migrator   # deny
bao token capabilities "$T" secret/data/assetflow/database   # read
```

Secret layout under `secret/` (KV v2):

| Path | Keys | Written by |
| --- | --- | --- |
| `assetflow/database` | runtime database role credentials | operator |
| `assetflow/migrator` | migration role credentials | operator |
| `assetflow/postgres` | `superuser_password` | `openbao-apply.py --generate-missing` |
| `assetflow/smtp` | SMTP relay credentials | operator |
| `assetflow/idp` | Zitadel issuer, project and client values | the Zitadel bootstrap ([Set up Zitadel](setup-zitadel.md)) |
| `assetflow/orgs/<organization_id>/channels/<channel_id>` | notification channel credentials | api (write-only); AssetFlow's worker reads them at send time |
| `assetflow/zitadel/masterkey` | `value` (32 characters; never changes after Zitadel's first start) | `openbao-apply.py --generate-missing` |
| `assetflow/zitadel/database` | `admin_password`, `user_password` | `openbao-apply.py --generate-missing` |
| `assetflow/zitadel/admin` | `initial_password` (changed at first sign-in) | `openbao-apply.py --generate-missing` |
| `assetflow/zitadel/bootstrap-key` | `key_json` (bootstrap machine user) | the Zitadel bootstrap |
| `assetflow/zitadel/automation-key` | `key_json` (`assetflow-automation`) | the Zitadel bootstrap |
| `assetflow/zitadel/organizations` | organization slug → Zitadel organization id | the Zitadel bootstrap |

To store a credential I write it myself, for example the SMTP relay (the key names here are an example; use the names your SMTP settings expect):

```bash
bao kv put secret/assetflow/smtp username=your-secret-8 password=your-secret-9
```

## Step 8: Start the rest of the stack

With the operator token in `BAO_TOKEN`, one command starts everything in order:

```bash
make up-full                      # add GENERATE_MISSING=1 on the very first run
```

`make up-full` runs five steps: (1) start OpenBao; (2) check that it is unsealed, and if not, stop and print
the unseal command; (3) `openbao-apply` with fresh secret ids; (4) start Zitadel and run the Zitadel
bootstrap ([Set up Zitadel](setup-zitadel.md)); (5) start AssetFlow. Step 5 waits for the API image,
which is added in setup plan P3-05.

By design (master plan §B11.4), the AssetFlow API refuses to start with the error code
`platform.secrets_unavailable` when OpenBao is sealed or unreachable; this behaviour is implemented with
the API in setup plan P3.

How containers get their values:

- `api`, `worker` and `migrator` log in with AppRole using `BAO_ROLE_ID_FILE` and `BAO_SECRET_ID_FILE`
  (files under `/run/secrets`) and keep secrets in memory.
- PostgreSQL and Zitadel get their values from OpenBao Agent sidecars (`postgres-secrets`,
  `zitadel-secrets`) that log in with their own AppRole and render files into a `tmpfs` volume, mounted
  read-only into the consumer. The agents keep running, so rotated values are rendered again.
  Reference: [OpenBao Agent](https://openbao.org/docs/agent-and-proxy/agent/).

## Verify

| Check | Command | Expected |
| --- | --- | --- |
| Unsealed | `docker compose -f deploy/compose.full.yml exec openbao bao status` | `Sealed false`, exit code 0 |
| Health endpoint | `curl --cacert deploy/.secrets/openbao-tls/ca.pem https://127.0.0.1:8200/v1/sys/health` | HTTP 200 |
| Configuration applied | `python scripts/openbao-apply.py` | `No changes.` |
| Least privilege | Step 7 capability checks | `deny` / `read` as shown |
| Root token revoked | `BAO_TOKEN=your-secret-6 bao token lookup` | HTTP 403 |
| Stack smoke test | `make smoke-full` | every check `PASS` |

`/v1/sys/health` status codes: 200 active and unsealed, 429 standby, 501 not initialized, 503 sealed.

## Customize for your installation

| What | Where | Notes |
| --- | --- | --- |
| Key shares and threshold | Step 4 `-key-shares` / `-key-threshold` | match the number of key holders you have |
| Auto-unseal | add a `seal` stanza to `openbao.hcl` | transit or a cloud KMS; removes the manual unseal |
| Certificate | `deploy/.secrets/openbao-tls/` | use your own CA in production |
| Raft node id and path | `storage "raft"` in `openbao.hcl` | change `node_id` per node when you run a cluster |
| Network range for AppRole binding | `ASSETFLOW_NET_CIDR` | set it to your compose or cluster subnet; `""` turns binding off |
| Token and secret id lifetimes | `ROLE_SETTINGS` in `scripts/openbao-apply.py` | shorter is safer; services renew periodic tokens |
| What a service may read | `deploy/openbao/policies/<service>.hcl` | keep policies read-only and per service |
| New service | add `deploy/openbao/policies/<name>.hcl` | the next `openbao-apply.py` run creates its AppRole |
| Lease TTLs | `default_lease_ttl`, `max_lease_ttl` in `openbao.hcl` | |

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `bao status` exit code 2, dependants never start | OpenBao is sealed (every restart seals it) | unseal (Step 4) |
| `x509: certificate signed by unknown authority` | client does not trust the local CA | set `BAO_CACERT=deploy/.secrets/openbao-tls/ca.pem` |
| AppRole login fails with `invalid secret id` | secret ids expire after 24 hours | `make openbao-apply ISSUE_SECRET_IDS=1`, then restart the service |
| AppRole login denied from a new network | CIDR binding | set `ASSETFLOW_NET_CIDR` to the new range and re-apply |
| API stops with `platform.secrets_unavailable` (from P3) | OpenBao sealed or unreachable | unseal or fix the network, then restart the API |
| Permission denied reading a path | the service policy does not allow it | add the path to that service's policy and re-apply |

## References

- OpenBao configuration: https://openbao.org/docs/configuration/
- Raft storage: https://openbao.org/docs/configuration/storage/raft/
- TCP listener: https://openbao.org/docs/configuration/listener/tcp/
- Seal / auto-unseal: https://openbao.org/docs/configuration/seal/
- AppRole auth: https://openbao.org/docs/auth/approle/
- KV v2: https://openbao.org/docs/secrets/kv/kv-v2/
- Transit: https://openbao.org/docs/secrets/transit/
- Policies: https://openbao.org/docs/concepts/policies/
- OpenBao Agent: https://openbao.org/docs/agent-and-proxy/agent/
- Operator runbook in this repository: [docs/operations/openbao.md](../operations/openbao.md)
