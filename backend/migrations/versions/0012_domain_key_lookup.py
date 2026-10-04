# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""A narrow worker lookup of an organization's domain_key (§B5.2, §B7.3, M1.5-T3).

Revision ID: 0012_domain_key_lookup
Revises: 0011_notification_worker_grants
Create Date: 2026-10-04 00:00:12.000000

The automation subscriber needs an event's organization's `domain_key` to find its domain
template, but the worker role has no grant on `organizations` at all (it is not a per-row tenant
table the worker otherwise touches; only `assetflow_api` reads it, and `assetflow_resolver`'s
`platform.resolve_organization` is the one sign-in-time exception). Rather than widen the worker's
access to the whole row, this adds one more narrow SECURITY DEFINER function, the same pattern as
`platform.list_active_organizations()` (0009): owned by `assetflow_resolver`, callable only by
`assetflow_worker`, returning exactly the one column needed. `assetflow_resolver`'s own column
grant (0001) covers `id`, `idp_organization_id` and `status` only, so this adds `domain_key` to it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012_domain_key_lookup"
down_revision: str | None = "0011_notification_worker_grants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # assetflow_resolver's existing column grant (0001) covers id, idp_organization_id, status
    # only; the function body below needs domain_key too.
    op.execute("GRANT SELECT (domain_key) ON public.organizations TO assetflow_resolver")
    op.execute("""
CREATE FUNCTION platform.get_domain_key(p_organization_id uuid)
RETURNS text
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $fn$
    SELECT o.domain_key
    FROM public.organizations AS o
    WHERE o.id = p_organization_id
$fn$
""")
    op.execute("REVOKE ALL ON FUNCTION platform.get_domain_key(uuid) FROM PUBLIC")
    # A new owner needs CREATE on the schema; it is granted only for the ownership change.
    op.execute("GRANT CREATE ON SCHEMA platform TO assetflow_resolver")
    op.execute("ALTER FUNCTION platform.get_domain_key(uuid) OWNER TO assetflow_resolver")
    op.execute("REVOKE CREATE ON SCHEMA platform FROM assetflow_resolver")
    op.execute("REVOKE ALL ON FUNCTION platform.get_domain_key(uuid) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION platform.get_domain_key(uuid) TO assetflow_worker")


def downgrade() -> None:
    op.execute("DROP FUNCTION platform.get_domain_key(uuid)")
    op.execute("REVOKE SELECT (domain_key) ON public.organizations FROM assetflow_resolver")
