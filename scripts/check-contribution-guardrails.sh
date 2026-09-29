#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
# Runs check-contribution-guardrails.py with the first working Python 3.10+ (python3, python, or the Windows py launcher).
# Works on Linux, macOS and Git Bash on Windows, where "python3" may be a Store alias that does not run.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="${SCRIPT_DIR}/check-contribution-guardrails.py"
PY_OK='import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'

if [ -n "${PYTHON:-}" ]; then
  exec "${PYTHON}" "${SCRIPT}" "$@"
fi
for candidate in python3 python; do
  if command -v "${candidate}" >/dev/null 2>&1 && "${candidate}" -c "${PY_OK}" >/dev/null 2>&1; then
    exec "${candidate}" "${SCRIPT}" "$@"
  fi
done
if command -v py >/dev/null 2>&1 && py -3 -c "${PY_OK}" >/dev/null 2>&1; then
  exec py -3 "${SCRIPT}" "$@"
fi
echo "error: Python 3.10 or newer not found (tried PYTHON, python3, python, py -3)" >&2
exit 127
