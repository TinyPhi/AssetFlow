<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# Full profile startup

**Master plan:** §B11.4 startup flow, decision 51, M1.6-T8 (setup plan P2-12)
**Files:** `deploy/compose.full.yml`, `scripts/bootstrap.sh`, `scripts/bootstrap_zitadel.py`, `scripts/smoke-full.py`

Local development without OpenBao uses only the identity stack: `scripts/bootstrap.sh` (Windows:
`setup.bat`) or `make bootstrap`, see `docs/operations/zitadel.md` section 2.

## 0. Ports and names (running next to other projects)

AssetFlow publishes its host ports **above 9000** so it never collides with, or silently reuses,
another project's PostgreSQL (5432), Zitadel (8080), OpenBao (8200) and the like on the same machine.
Container-internal ports are unchanged. Every host port can be moved with the variable in the table
(in the shell or in `.env.local`).

| Service | Host address | Variable | Profile |
| --- | --- | --- | --- |
| OpenBao | `https://127.0.0.1:19200` | `OPENBAO_HOST_PORT` | full |
| PostgreSQL | `127.0.0.1:15432` | `POSTGRES_HOST_PORT` | full |
| Zitadel (browser URL and API) | `http://localhost:19081` | `ZITADEL_EXTERNALPORT` | full, identity |
| AssetFlow API | `http://localhost:18080` | `API_HOST_PORT` | full |

`ZITADEL_EXTERNALPORT` is also the port in Zitadel's own external URL, so the issuer, the browser and
the bootstrap script all follow the one variable.

Before starting, `make up-full` and `make up-identity` run `scripts/check-ports.py`. It stops, with the
port and the variable that moves it, when a chosen port is at or below 9000, chosen twice, or already
in use by something that is not part of this project. A port held by a running container of this
project is fine (you are starting the stack again). Nothing is started and no container is touched
when it fails.

Every service of both stacks carries the label `com.tinyphi.project=assetflow`. The full stack is the
compose project `assetflow`; the identity stack keeps its own project name `assetflow-dev` so that
`make down-identity` can stop the development Zitadel without stopping the full stack, and the other
way round. `make down` and `make down-identity` act only on these two projects.

## 1. Order

Compose enforces the order with `depends_on` and health conditions:

```
openbao ──(operators unseal; healthy = unsealed)
  ├─> postgres-secrets (agent, healthy = file rendered) ─> postgres (healthy = pg_isready)
  └─> zitadel-secrets  (agent, healthy = files rendered) ─> zitadel-db (healthy)
        ─> zitadel (start-from-init: init + setup + start; healthy = zitadel ready)
              ─> zitadel-bootstrap (one-off: make zitadel-apply; results into OpenBao)
api ── waits for openbao, postgres and zitadel to be healthy
```

This follows the four steps of §B11.4:

1. All credentials are in OpenBao beforehand (`openbao-apply --generate-missing`, operators,
   the Zitadel bootstrap `make zitadel-apply`).
2. The start procedure gives each container only its own AppRole login, as read-only files
   (`/run/secrets/<name>_role_id`, `/run/secrets/<name>_secret_id`), and never copies a
   credential into environment variables, `.env` files or images.
3. At boot the API (and later the worker) logs in to OpenBao and reads what it needs into
   memory. If OpenBao is sealed or unreachable, boot stops with `platform.secrets_unavailable`.
   PostgreSQL and Zitadel get their values from OpenBao Agent sidecars as tmpfs files.
4. Tokens are periodic and renewed; agents re-render files after a rotation.

## 2. Start procedure

From the repository root (first time: see `docs/operations/openbao.md` sections 2 to 4):

```bash
sh deploy/openbao/gen-dev-tls.sh                          # once; production: your CA's files
docker compose -f deploy/compose.full.yml up -d openbao
# unseal (docs/operations/openbao.md section 3)
export BAO_ADDR=https://127.0.0.1:19200 BAO_CACERT=deploy/.secrets/openbao-tls/ca.pem
read -rs BAO_TOKEN && export BAO_TOKEN                    # operator token
python scripts/openbao-apply.py --issue-secret-ids        # fresh, short-lived secret ids
docker compose -f deploy/compose.full.yml up -d --wait zitadel
ASSETFLOW_ENV=production make zitadel-apply               # first time, and after config changes
docker compose -f deploy/compose.full.yml up -d --wait
python scripts/smoke-full.py
```

The same order with `make` (it stops at the unseal step while OpenBao is sealed and tells you what
to run; unseal, then run it again):

```bash
read -rs BAO_TOKEN && export BAO_TOKEN
make up-full                      # first time: make up-full GENERATE_MISSING=1 with the root token
make smoke-full
```

Or the identity part in one command (OpenBao, openbao-apply, Zitadel, bootstrap):

```bash
ASSETFLOW_ENV=production scripts/bootstrap.sh
```

Non-secret settings can be overridden from the shell: `ZITADEL_DOMAIN`,
`ZITADEL_EXTERNALPORT`, `ZITADEL_EXTERNALSECURE`, `ZITADEL_TLS_MODE` (`external` behind TLS), `APP_URL`, `API_URL`, `OPENBAO_HOST_PORT`, `POSTGRES_HOST_PORT`,
`API_HOST_PORT`, `ASSETFLOW_NET_CIDR`, `ASSETFLOW_ENV`.

## 3. Smoke test

`scripts/smoke-full.py` (or `sh scripts/smoke-full.sh`) exits non-zero on the first failure:

1. OpenBao initialized and unsealed;
2. Zitadel `/debug/healthz` is `ok` and its issuer equals the configured public URL;
3. AssetFlow `/healthz` is 200 and every reported provider is healthy (`--skip-api` until the
   API image exists);
4. no running container has a credential-like variable in its environment.

## 4. Sealed OpenBao

```bash
docker compose -f deploy/compose.full.yml restart openbao        # comes back sealed
docker compose -f deploy/compose.full.yml restart api
python scripts/smoke-full.py --expect-sealed   # sealed, and api log shows platform.secrets_unavailable
```

While sealed, the `openbao` health check fails, so no dependent container is (re)started,
and running services answer `503 platform.secrets_unavailable` for anything that needs a
secret (§B11.4). Unseal to recover.
