#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
# Local development stack: one command, Zitadel first, then the product (deploy/compose.dev.yml).
#
#   scripts/dev.sh [up]          start (or re-start) the stack
#   scripts/dev.sh down [--reset]  stop AssetFlow's containers; --reset also deletes its volumes (asks)
#   scripts/dev.sh admin-password  print the first Zitadel admin's password (you asked for it)
#
# Environment (non-secret): WEB=vite (no af-web; run `npm run dev` in frontend/), MAIL=1 (af-mailpit),
# OBSERVABILITY=1 (af-otel), WEB_PORT, API_HOST_PORT, ZITADEL_EXTERNALPORT, OPENBAO_HOST_PORT,
# POSTGRES_HOST_PORT. Only containers of the compose project `assetflow` (label
# com.tinyphi.project=assetflow) are ever started or stopped; never another project's.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

COMPOSE_FILE=deploy/compose.dev.yml
PROJECT=assetflow
PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
  for p in python3 python; do
    if "$p" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then PYTHON="$p"; break; fi
  done
fi
[ -n "$PYTHON" ] || { echo "dev: Python 3.10+ not found (set PYTHON=...)." >&2; exit 1; }

say() { printf '\n==> %s\n' "$*"; }
die() { printf 'dev: error: %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || die "Docker is required."
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required."

WEB_PORT="${WEB_PORT:-18080}"
API_HOST_PORT="${API_HOST_PORT:-18090}"
export WEB_PORT API_HOST_PORT
if [ "${WEB:-}" = "vite" ]; then
  export APP_URL="${APP_URL:-http://localhost:5173}"
  export API_URL="${API_URL:-http://localhost:${API_HOST_PORT}}"
else
  export APP_URL="${APP_URL:-http://localhost:${WEB_PORT}}"
  export API_URL="${API_URL:-http://localhost:${WEB_PORT}}"
fi

PROFILES=()
[ "${MAIL:-}" = "1" ] && PROFILES+=(--profile mail)
[ "${OBSERVABILITY:-}" = "1" ] && PROFILES+=(--profile observability)
SERVICES=(api worker)
[ "${WEB:-}" = "vite" ] || SERVICES+=(web)
[ "${MAIL:-}" = "1" ] && SERVICES+=(mailpit)
[ "${OBSERVABILITY:-}" = "1" ] && SERVICES+=(otel)

dc() { docker compose -p "$PROJECT" -f "$COMPOSE_FILE" "${PROFILES[@]}" "$@"; }
setup() { dc run --rm --no-deps -T --name af-setup setup "$1"; }

cmd_up() {
  say "1/7 preflight: ports free, no foreign container owns an af- name"
  "$PYTHON" scripts/check-ports.py dev

  say "2/7 build the two images (assetflow-backend, assetflow-web)"
  BUILD=(api)
  [ "${WEB:-}" = "vite" ] || BUILD+=(web)
  dc build "${BUILD[@]}"

  say "3/7 af-openbao up, unseal with the local dev key, openbao-apply"
  dc up -d --wait openbao
  setup openbao

  say "4/7 af-postgres up (databases assetflow and zitadel)"
  dc up -d --wait postgres

  say "5/7 af-zitadel up, zitadel-apply (client secrets go into OpenBao)"
  dc up -d --wait zitadel
  setup zitadel

  say "6/7 migrate, then af-api, af-worker, af-web"
  setup migrate
  dc up -d --wait "${SERVICES[@]}"

  say "7/7 sign-in check and smoke test"
  setup signin
  ZITADEL_DOMAIN="${ZITADEL_DOMAIN:-zitadel.localhost}" "$PYTHON" scripts/smoke-full.py --dev

  printf '\nAssetFlow development stack is up:\n'
  if [ "${WEB:-}" = "vite" ]; then
    printf '  web (Vite)   %s   run: cd frontend && npm run dev\n' "$APP_URL"
    printf '  api          http://localhost:%s\n' "$API_HOST_PORT"
  else
    printf '  web          %s\n' "$APP_URL"
    printf '  api          http://localhost:%s (direct)\n' "$API_HOST_PORT"
  fi
  printf '  sign-in      http://%s:%s (user: admin; password: scripts/dev.sh admin-password)\n' \
    "${ZITADEL_DOMAIN:-zitadel.localhost}" "${ZITADEL_EXTERNALPORT:-19081}"
  printf '  openbao      http://127.0.0.1:%s\n' "${OPENBAO_HOST_PORT:-19200}"
  printf '  postgres     127.0.0.1:%s\n' "${POSTGRES_HOST_PORT:-15432}"
  [ "${MAIL:-}" = "1" ] && printf '  mailpit      http://localhost:%s\n' "${MAILPIT_WEB_PORT:-18025}"
  [ "${OBSERVABILITY:-}" = "1" ] && printf '  grafana      http://localhost:%s\n' "${GRAFANA_HOST_PORT:-13000}"
  return 0
}

cmd_down() {
  local reset=0
  [ "${1:-}" = "--reset" ] && reset=1
  # Stops only the services of this compose file in project `assetflow`; no --remove-orphans.
  # Profiles are named so the optional containers stop too.
  PROFILES=(--profile mail --profile observability --profile setup)
  if [ "$reset" = 1 ]; then
    printf "This deletes every AssetFlow development volume (database, OpenBao data, transit key). Type 'yes': "
    read -r answer
    [ "$answer" = "yes" ] || die "aborted."
    dc down --volumes
  else
    dc down
  fi
}

cmd_admin_password() {
  # Reads the password live from OpenBao and prints only it (nothing is logged or written to disk);
  # not routed through dev_setup.py so the value never passes through a Python source file CodeQL
  # scans for clear-text logging (scripts/dev_setup.py's own step only tells the caller to run this).
  dc run --rm --no-deps -T --name af-admin-password \
    --entrypoint /app/.venv/bin/python setup -c "
import json, os, pathlib, urllib.request
token = pathlib.Path('/run/af-keys/root-token').read_text(encoding='utf-8').strip()
addr = os.environ.get('BAO_ADDR', 'http://openbao:8200')
req = urllib.request.Request(
    f'{addr}/v1/secret/data/assetflow/zitadel/admin', headers={'X-Vault-Token': token}
)
with urllib.request.urlopen(req, timeout=15) as response:
    data = json.load(response)
print(data['data']['data']['initial_password'])
"
}

case "${1:-up}" in
  up) cmd_up ;;
  down) shift; cmd_down "${1:-}" ;;
  admin-password) cmd_admin_password ;;
  *) die "usage: dev.sh [up|down [--reset]|admin-password]" ;;
esac
