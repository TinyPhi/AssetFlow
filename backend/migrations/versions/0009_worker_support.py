# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Support for the worker process and the outbox dispatcher (§B9.3, §B6.2, M1.5-T1).

Revision ID: 0009_worker_support
Revises: 0008_org_settings_support
Create Date: 2026-10-04 00:00:09.000000

  * `platform.list_active_organizations()` returns the ids of active organizations so a worker
    sweep can visit each organization in its own short transaction under its own context. It is a
    SECURITY DEFINER function owned by `assetflow_resolver` (like `platform.resolve_organization`),
    because `organizations` has forced row-level security and only that role has a read policy and
    a column grant on it. Only `assetflow_worker` may execute it.
  * `outbox.dead_lettered_at` marks an event that failed `workers.outbox.max_attempts` times. The
    partial index serves the dispatcher's claim query (organization_id first, §C4.8).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009_worker_support"
down_revision: str | None = "0008_org_settings_support"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
CREATE FUNCTION platform.list_active_organizations()
RETURNS SETOF uuid
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $fn$
    SELECT o.id
    FROM public.organizations AS o
    WHERE o.status = 'active'
    ORDER BY o.id
$fn$
""")
    op.execute("REVOKE ALL ON FUNCTION platform.list_active_organizations() FROM PUBLIC")
    # A new owner needs CREATE on the schema; it is granted only for the ownership change.
    op.execute("GRANT CREATE ON SCHEMA platform TO assetflow_resolver")
    op.execute("ALTER FUNCTION platform.list_active_organizations() OWNER TO assetflow_resolver")
    op.execute("REVOKE CREATE ON SCHEMA platform FROM assetflow_resolver")
    op.execute("REVOKE ALL ON FUNCTION platform.list_active_organizations() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION platform.list_active_organizations() TO assetflow_worker")

    op.execute("ALTER TABLE public.outbox ADD COLUMN dead_lettered_at timestamptz NULL")
    op.execute(
        "CREATE INDEX ix_outbox__organization_id_pending ON public.outbox (organization_id, created_at) "
        "WHERE processed_at IS NULL AND dead_lettered_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX public.ix_outbox__organization_id_pending")
    op.execute("ALTER TABLE public.outbox DROP COLUMN dead_lettered_at")
    op.execute("DROP FUNCTION platform.list_active_organizations()")
