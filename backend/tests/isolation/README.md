<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->
# `backend/tests/isolation`

Multi-tenant isolation suite (§C5.4, §C8.5). Every test runs against a **real PostgreSQL** and connects
as a LOGIN user that belongs to one group role (`assetflow_api`, `assetflow_worker`,
`assetflow_readonly`, `assetflow_migrator`), never as the superuser.

Where the server comes from (`pg_harness.py`):

1. `ASSETFLOW_TEST_DATABASE_URL`: a superuser DSN of a disposable server;
2. in GitHub Actions only, `ASSETFLOW_DATABASE_URL` (the job's `postgres` service);
3. otherwise a throwaway `postgres:16-alpine` container via the docker CLI, on a random local port,
   with a superuser password generated for the run; it is removed afterwards.

With none of these the suite is skipped with the reason (in CI it fails). Each run creates its own
database, runs `alembic upgrade head` and drops everything at the end. Roles are cluster-wide and
`test_migrations_roundtrip.py` drops them, so point `ASSETFLOW_TEST_DATABASE_URL` only at a
disposable server.

Run: `make test-isolation` (`cd backend && uv run pytest -q tests/isolation tests/scope`).
