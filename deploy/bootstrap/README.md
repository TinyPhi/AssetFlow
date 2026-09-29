<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# `deploy/bootstrap`

Environment bootstrap scripts, local secret seeding, and initial migration runners (§B13.1).

- `Dockerfile`: image of `scripts/bootstrap_zitadel.py` (python:3.12-slim + uv), used as the
  `zitadel-bootstrap` service of `deploy/compose.identity.yml` and `deploy/compose.full.yml`.
  Build context is the repository root; `Dockerfile.dockerignore` sends only the script.
- Entry points: `scripts/bootstrap.sh`, `setup.bat`, `make bootstrap`, `make zitadel-apply`
  (`docs/operations/zitadel.md`).
