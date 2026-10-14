# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Organizations platform table and the sign-in resolver (§B5.2, §B10, §C4.8).

Revision ID: 0001_organizations
Revises: 0000_roles
Create Date: 2026-09-30 00:00:01.000000

`public.organizations` is the one platform table: it is scoped on `id` instead of `organization_id`,
so the application can read only the organization of the current context. Before a context exists
(at sign-in), the API finds an organization only through `platform.resolve_organization()`, a
SECURITY DEFINER function that returns `(id, status)` for exactly one IdP organization.

The function is owned by `assetflow_resolver`, a NOLOGIN role with no BYPASSRLS. Under FORCE ROW
LEVEL SECURITY that owner reads through one narrow policy (`FOR SELECT TO assetflow_resolver`) and a
column grant limited to `id`, `idp_organization_id` and `status`. No role inherits assetflow_resolver
(0000 grants it to the migrator WITH INHERIT FALSE), so the policy reaches the function owner only.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001_organizations"
down_revision: str | None = "0000_roles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE public.organizations (
    -- check-migrations: platform-table
    id uuid NOT NULL,
    slug text NOT NULL,
    name text NOT NULL,
    idp_organization_id text NOT NULL,
    domain_key text NOT NULL,
    settings jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text NOT NULL DEFAULT 'active',
    version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT organizations_pkey PRIMARY KEY (id),
    CONSTRAINT organizations_slug_key UNIQUE (slug),
    CONSTRAINT organizations_idp_organization_id_key UNIQUE (idp_organization_id),
    CONSTRAINT organizations_status_check CHECK (status IN ('active', 'suspended', 'archived')),
    CONSTRAINT organizations_settings_object_check CHECK (jsonb_typeof(settings) = 'object'),
    CONSTRAINT organizations_version_check CHECK (version >= 1)
)
""")
    # Owned by the group role, not by whichever login user ran the migration.
    op.execute("ALTER TABLE public.organizations OWNER TO assetflow_migrator")

    op.execute("ALTER TABLE public.organizations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.organizations FORCE ROW LEVEL SECURITY")

    op.execute("""
CREATE POLICY organizations_select ON public.organizations
    FOR SELECT
    USING (id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY organizations_insert ON public.organizations
    FOR INSERT
    WITH CHECK (id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY organizations_update ON public.organizations
    FOR UPDATE
    USING (id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
    WITH CHECK (id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY organizations_delete ON public.organizations
    FOR DELETE
    USING (id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    # The resolver's read path (§B5.2). Only the function owner has this role; no login user does.
    op.execute("""
CREATE POLICY organizations_resolver_select ON public.organizations
    FOR SELECT
    TO assetflow_resolver
    USING (true)
""")

    op.execute("GRANT SELECT ON public.organizations TO assetflow_api")
    op.execute("GRANT ALL ON public.organizations TO assetflow_migrator")
    op.execute("GRANT SELECT (id, idp_organization_id, status) ON public.organizations TO assetflow_resolver")

    op.execute("CREATE SCHEMA platform AUTHORIZATION assetflow_migrator")
    op.execute("REVOKE ALL ON SCHEMA platform FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA platform TO assetflow_api")

    op.execute("""
CREATE FUNCTION platform.resolve_organization(p_idp_organization_id text)
RETURNS TABLE (id uuid, status text)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $fn$
    SELECT o.id, o.status
    FROM public.organizations AS o
    WHERE o.idp_organization_id = p_idp_organization_id
$fn$
""")
    op.execute("REVOKE ALL ON FUNCTION platform.resolve_organization(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION platform.resolve_organization(text) TO assetflow_api")
    # A new owner needs CREATE on the schema; it is granted only for the ownership change.
    op.execute("GRANT CREATE ON SCHEMA platform TO assetflow_resolver")
    op.execute("ALTER FUNCTION platform.resolve_organization(text) OWNER TO assetflow_resolver")
    op.execute("REVOKE CREATE ON SCHEMA platform FROM assetflow_resolver")


def downgrade() -> None:
    op.execute("DROP FUNCTION platform.resolve_organization(text)")
    op.execute("DROP SCHEMA platform")
    op.execute("DROP TABLE public.organizations")
