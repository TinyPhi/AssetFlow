#!/usr/bin/env sh
# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
# Generate a local CA and OpenBao server certificate for development and evaluation
# (§B11.4). Production installs place a CA-signed certificate at the same paths.
# Output: deploy/.secrets/openbao-tls/{ca.pem,server.pem,server-key.pem} (git-ignored).
# Idempotent: existing files are kept unless --force is given.
set -eu

here="$(cd "$(dirname "$0")" && pwd)"
out="${here}/../.secrets/openbao-tls"
days="${OPENBAO_TLS_DAYS:-825}"
# Git Bash on Windows rewrites a leading "/" as a path; "//" keeps "/CN=..." intact.
subj_prefix=""
case "$(uname -s)" in MINGW*|MSYS*) subj_prefix="/" ;; esac

if [ -s "${out}/server.pem" ] && [ "${1:-}" != "--force" ]; then
  echo "OpenBao TLS files already exist in ${out} (use --force to replace)."
  exit 0
fi

umask 077
mkdir -p "${out}"
chmod 700 "${out}" "${here}/../.secrets"
tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT

cat > "${tmp}/server.ext" <<EXT
basicConstraints=CA:FALSE
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:openbao,DNS:localhost,IP:127.0.0.1
EXT

openssl req -x509 -newkey rsa:4096 -sha256 -nodes -days "${days}" \
  -subj "${subj_prefix}/CN=AssetFlow local OpenBao CA" \
  -keyout "${tmp}/ca-key.pem" -out "${out}/ca.pem"
openssl req -newkey rsa:2048 -sha256 -nodes -subj "${subj_prefix}/CN=openbao" \
  -keyout "${out}/server-key.pem" -out "${tmp}/server.csr"
openssl x509 -req -in "${tmp}/server.csr" -CA "${out}/ca.pem" -CAkey "${tmp}/ca-key.pem" \
  -CAserial "${tmp}/ca.srl" -CAcreateserial -days "${days}" -sha256 -extfile "${tmp}/server.ext" \
  -out "${out}/server.pem"

# Compose bind-mounts these files; the OpenBao container user (uid 100) must read them.
# The parent directory stays 0700, so other host users cannot.
chmod 644 "${out}/ca.pem" "${out}/server.pem" "${out}/server-key.pem"
echo "Wrote ${out}/ca.pem, server.pem, server-key.pem (CA key discarded)."
