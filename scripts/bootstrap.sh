#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
#
# One-command identity setup (Linux, macOS, WSL2, Git Bash). Windows: setup.bat.
# docs/operations/zitadel.md. Needs only Docker (Compose v2); no host Python.
#
#   scripts/bootstrap.sh              development: .env.local secrets, Zitadel, bootstrap
#   scripts/bootstrap.sh --dry-run    print what the bootstrap would change
#   scripts/bootstrap.sh --reset      development: delete the local Zitadel volumes first
#   ASSETFLOW_ENV=production scripts/bootstrap.sh
#                                     full profile: OpenBao (must be unsealed, BAO_TOKEN set),
#                                     openbao-apply, Zitadel, bootstrap into OpenBao
#
# Re-runs are safe: existing secrets are reused and the bootstrap changes only what differs.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"
export MSYS_NO_PATHCONV=1 # Git Bash: keep container paths such as /zitadel/bootstrap as they are

RESET=0
APPLY_ARGS=()
for arg in "$@"; do
  case "${arg}" in
    --reset) RESET=1 ;;
    --dry-run) APPLY_ARGS+=(--dry-run) ;;
    -h | --help) sed -n '5,15p' "$0"; exit 0 ;;
    *) echo "unknown option: ${arg} (see --help)" >&2; exit 2 ;;
  esac
done

say() { printf '\n==> %s\n' "$1"; }
fail() { printf '\nerror: %s\n' "$1" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || fail "Docker is required (https://docs.docker.com/get-docker/)."
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is required (docker compose)."

explain_start_failure() {
  local logs="$1"
  if grep -qiE 'masterkey|cipher: message authentication failed|unable to decrypt' <<<"${logs}"; then
    echo "Zitadel cannot decrypt its data: the masterkey differs from the one the volume was created with." >&2
    echo "Restore the original value, or (development only) start over with: scripts/bootstrap.sh --reset" >&2
  elif grep -qiE 'password authentication failed' <<<"${logs}"; then
    echo "Zitadel cannot log in to its database: the database passwords differ from the volume's." >&2
    echo "Restore the original values, or (development only) start over with: scripts/bootstrap.sh --reset" >&2
  fi
}

# ---------------------------------------------------------------- production (full profile)
if [ "${ASSETFLOW_ENV:-development}" = "production" ]; then
  [ "${RESET}" = 1 ] && fail "--reset is for local development only."
  [ -n "${BAO_TOKEN:-}" ] || fail "set BAO_TOKEN (operator token): read -rs BAO_TOKEN && export BAO_TOKEN"
  [ -f deploy/.secrets/openbao-tls/ca.pem ] || fail "no OpenBao TLS files; see docs/operations/openbao.md section 2."
  DC=(docker compose -p assetflow -f deploy/compose.full.yml)
  say "1/4 OpenBao"
  "${DC[@]}" up -d openbao
  "${DC[@]}" exec -T openbao bao status >/dev/null 2>&1 ||
    fail "OpenBao is not initialized or is sealed. Unseal it (docs/operations/openbao.md section 3), then run this again."
  say "2/4 openbao-apply (secrets generated once, fresh secret ids)"
  bash scripts/openbao-apply.sh --generate-missing --issue-secret-ids
  say "3/4 Zitadel"
  if ! "${DC[@]}" up -d --wait zitadel; then
    explain_start_failure "$("${DC[@]}" logs --tail 200 zitadel 2>&1)"
    fail "Zitadel did not become healthy; see: ${DC[*]} logs zitadel"
  fi
  say "4/4 Zitadel bootstrap (results go to OpenBao, never to files)"
  "${DC[@]}" --profile bootstrap run --rm --build zitadel-bootstrap apply ${APPLY_ARGS[@]+"${APPLY_ARGS[@]}"}
  say "Done. Console: see the line above. Admin initial password: bao kv get -field=initial_password secret/assetflow/zitadel/admin"
  exit 0
fi

# ---------------------------------------------------------------- development
ENV_FILE=".env.local"
DC=(docker compose -f deploy/compose.identity.yml --env-file "${ENV_FILE}")
if [ ! -f "${ENV_FILE}" ]; then
  : >"${ENV_FILE}"
  chmod 600 "${ENV_FILE}" 2>/dev/null || true
fi

if [ "${RESET}" = 1 ]; then
  say "Reset: deleting the local Zitadel containers and volumes (secrets in ${ENV_FILE} are kept)"
  "${DC[@]}" --profile bootstrap down -v --remove-orphans
fi

say "1/4 Bootstrap image"
"${DC[@]}" --profile bootstrap build zitadel-bootstrap

say "2/4 Local secrets (${ENV_FILE}, git-ignored)"
# Also checks that an existing Zitadel volume was created with the masterkey in .env.local.
"${DC[@]}" --profile bootstrap run --rm --no-deps zitadel-bootstrap init-env --marker-dir /zitadel/bootstrap

say "3/4 Zitadel (first start takes about a minute)"
if ! "${DC[@]}" up -d --wait zitadel; then
  explain_start_failure "$("${DC[@]}" logs --tail 200 zitadel 2>&1)"
  fail "Zitadel did not become healthy; see: ${DC[*]} logs zitadel"
fi

say "4/4 Zitadel bootstrap"
"${DC[@]}" --profile bootstrap run --rm zitadel-bootstrap apply ${APPLY_ARGS[@]+"${APPLY_ARGS[@]}"}

cat <<EOF

  =============================================================
   Identity is ready (local development).
   Console:   http://${ZITADEL_DOMAIN:-localhost}:${ZITADEL_EXTERNALPORT:-19081}/ui/console
   Admin:     login name printed above; password = ZITADEL_ADMIN_PASSWORD in ${ENV_FILE}
   Results:   ZITADEL_* in ${ENV_FILE} (project id, client ids and secrets, organization ids)
   Stop:      make down-identity        Start again: make up-identity
  =============================================================
EOF
