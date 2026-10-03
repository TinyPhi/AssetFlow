# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Support for `assetflow org create` (§B5.2, §B5.5, M1.4-T2).

Revision ID: 0007_org_create_support
Revises: 0006_audit_store
Create Date: 2026-10-03 00:00:07.000000

`organizations` had SELECT only for `assetflow_api` (no code created organizations before this
plan). The CLI runs as `assetflow_api`, outside any request handler, and opens a `tenant_transaction`
stamped with the new organization's own id before the INSERT, so the existing fail-closed
`organizations_insert` policy (`id = app.organization_id`) is what actually authorizes the row: the
grant below only lifts the privilege check, not the isolation guarantee.

`platform.find_organization_id` mirrors `platform.resolve_organization` (0001): a narrow
SECURITY DEFINER function owned by `assetflow_resolver`, so the CLI can check whether a slug is
already taken before it knows the organization's id (needed for idempotency), without any role
being able to SELECT the table outside its own organization context.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007_org_create_support"
down_revision: str | None = "0006_audit_store"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("GRANT INSERT ON public.organizations TO assetflow_api")
    # 0001 granted assetflow_resolver only (id, idp_organization_id, status); this function also
    # filters on slug, so it needs that column too (column grants are additive).
    op.execute("GRANT SELECT (slug) ON public.organizations TO assetflow_resolver")

    op.execute("""
CREATE FUNCTION platform.find_organization_id(p_slug text)
RETURNS uuid
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $fn$
    SELECT o.id
    FROM public.organizations AS o
    WHERE o.slug = p_slug
$fn$
""")
    op.execute("REVOKE ALL ON FUNCTION platform.find_organization_id(text) FROM PUBLIC")
    # A new owner needs CREATE on the schema; it is granted only for the ownership change.
    op.execute("GRANT CREATE ON SCHEMA platform TO assetflow_resolver")
    op.execute("ALTER FUNCTION platform.find_organization_id(text) OWNER TO assetflow_resolver")
    op.execute("REVOKE CREATE ON SCHEMA platform FROM assetflow_resolver")
    op.execute("REVOKE ALL ON FUNCTION platform.find_organization_id(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION platform.find_organization_id(text) TO assetflow_api")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS platform.find_organization_id(text)")
    op.execute("REVOKE SELECT (slug) ON public.organizations FROM assetflow_resolver")
    op.execute("REVOKE INSERT ON public.organizations FROM assetflow_api")
