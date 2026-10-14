# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Asset catalog reference tables, part a (master M2.1-T1, §B8.2, §C1.4, §C4.8, §C5.4).

Revision ID: 0016_asset_catalog_reference
Revises: 0015_preference_version
Create Date: 2026-10-04 00:00:16.000000

Creates the first half of the asset catalog's reference data (part b, assets/components/meters,
is P8-03):
  * asset_categories: a tree (ltree materialized path, like org_units/locations), each node
    optionally overriding the tag prefix and default criticality the domain template sets, and
    naming the team responsible for it.
  * custom_field_definitions: per-category field declarations (seven engine field types - a fixed
    list, not domain data). Rule validation and encryption happen in the service layer (P8-04).
  * manufacturers, suppliers: flat reference tables with a trigram index for the catalog's fuzzy
    search box (§B8.1).

Every table has:
  * organization_id uuid NOT NULL referencing public.organizations(id)
  * ENABLE ROW LEVEL SECURITY and FORCE ROW LEVEL SECURITY
  * Four fail-closed policies for SELECT, INSERT, UPDATE, DELETE, named rls_<table>_<op> (master
    §C1.4; the existing org-structure/access tables from 0001-0003 predate this convention and are
    named `<table>_<op>` - an open point already flagged in the plan for the owner to schedule a
    rename of the old ones, not addressed here)
  * An organization_id-first index or unique constraint
  * A `version` column for optimistic concurrency (§B8.2 says every asset-catalog row has one)

No `updated_at` trigger: no table anywhere in this schema has one (outbox, organization_modules,
members, and 0010's notification tables all set `updated_at` with a plain application UPDATE); a
`fn_set_updated_at` trigger function does not exist in the codebase, so these tables follow the
same convention rather than introducing one single-handedly (same call 0010 made).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016_asset_catalog_reference"
down_revision: str | None = "0015_preference_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_asset_categories() -> None:
    """Asset_categories: a tree, like org_units/locations (§B8.1, §B8.2)."""
    op.execute("""
CREATE TABLE public.asset_categories (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    parent_id uuid NULL,
    path ltree NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    tag_prefix text NULL,
    default_criticality text NULL,
    responsible_team_id uuid NULL,
    status text NOT NULL DEFAULT 'active',
    version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT asset_categories_pkey PRIMARY KEY (id),
    CONSTRAINT uq_asset_categories__organization_id_id UNIQUE (organization_id, id),
    CONSTRAINT uq_asset_categories__organization_id_code UNIQUE (organization_id, code),
    CONSTRAINT fk_asset_categories__organization_id__organizations
        FOREIGN KEY (organization_id) REFERENCES public.organizations (id) ON DELETE RESTRICT,
    CONSTRAINT fk_asset_categories__parent_id__asset_categories
        FOREIGN KEY (organization_id, parent_id)
            REFERENCES public.asset_categories (organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_asset_categories__responsible_team_id__teams
        FOREIGN KEY (organization_id, responsible_team_id)
            REFERENCES public.teams (organization_id, id) ON DELETE SET NULL,
    CONSTRAINT ck_asset_categories__status CHECK (status IN ('active', 'archived')),
    CONSTRAINT ck_asset_categories__version CHECK (version >= 1)
)
""")
    op.execute("ALTER TABLE public.asset_categories OWNER TO assetflow_migrator")
    op.execute("ALTER TABLE public.asset_categories ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.asset_categories FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE INDEX ix_asset_categories__organization_id_parent_id "
        "ON public.asset_categories (organization_id, parent_id)"
    )
    op.execute(
        "CREATE INDEX ix_asset_categories__organization_id_path "
        "ON public.asset_categories USING gist (organization_id, path)"
    )

    op.execute("""
CREATE POLICY rls_asset_categories_select ON public.asset_categories
    FOR SELECT
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY rls_asset_categories_insert ON public.asset_categories
    FOR INSERT
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY rls_asset_categories_update ON public.asset_categories
    FOR UPDATE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY rls_asset_categories_delete ON public.asset_categories
    FOR DELETE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")

    op.execute("GRANT SELECT, INSERT, UPDATE ON public.asset_categories TO assetflow_api")
    op.execute("GRANT SELECT ON public.asset_categories TO assetflow_worker")
    op.execute("GRANT SELECT ON public.asset_categories TO assetflow_readonly")
    op.execute("GRANT ALL ON public.asset_categories TO assetflow_migrator")


def _create_custom_field_definitions() -> None:
    """Custom_field_definitions: per-category field declarations (§B8.1)."""
    op.execute("""
CREATE TABLE public.custom_field_definitions (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    category_id uuid NOT NULL,
    key text NOT NULL,
    label text NOT NULL,
    field_type text NOT NULL,
    is_required boolean NOT NULL DEFAULT false,
    rules jsonb NOT NULL DEFAULT '{}'::jsonb,
    is_unique boolean NOT NULL DEFAULT false,
    is_encrypted boolean NOT NULL DEFAULT false,
    position integer NOT NULL DEFAULT 0,
    status text NOT NULL DEFAULT 'active',
    version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT custom_field_definitions_pkey PRIMARY KEY (id),
    CONSTRAINT uq_custom_field_definitions__organization_id_id UNIQUE (organization_id, id),
    CONSTRAINT uq_custom_field_definitions__organization_id_category_id_key
        UNIQUE (organization_id, category_id, key),
    CONSTRAINT fk_custom_field_definitions__organization_id__organizations
        FOREIGN KEY (organization_id) REFERENCES public.organizations (id) ON DELETE RESTRICT,
    CONSTRAINT fk_custom_field_definitions__category_id__asset_categories
        FOREIGN KEY (organization_id, category_id)
            REFERENCES public.asset_categories (organization_id, id) ON DELETE CASCADE,
    CONSTRAINT ck_custom_field_definitions__key_format CHECK (key ~ '^[a-z][a-z0-9_]*$'),
    CONSTRAINT ck_custom_field_definitions__field_type
        CHECK (field_type IN ('text', 'number', 'date', 'boolean', 'select', 'multi_select', 'json')),
    CONSTRAINT ck_custom_field_definitions__rules_object CHECK (jsonb_typeof(rules) = 'object'),
    CONSTRAINT ck_custom_field_definitions__status CHECK (status IN ('active', 'archived')),
    CONSTRAINT ck_custom_field_definitions__version CHECK (version >= 1)
)
""")
    op.execute("ALTER TABLE public.custom_field_definitions OWNER TO assetflow_migrator")
    op.execute("ALTER TABLE public.custom_field_definitions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.custom_field_definitions FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE INDEX ix_custom_field_definitions__organization_id_category_id "
        "ON public.custom_field_definitions (organization_id, category_id)"
    )

    op.execute("""
CREATE POLICY rls_custom_field_definitions_select ON public.custom_field_definitions
    FOR SELECT
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY rls_custom_field_definitions_insert ON public.custom_field_definitions
    FOR INSERT
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY rls_custom_field_definitions_update ON public.custom_field_definitions
    FOR UPDATE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY rls_custom_field_definitions_delete ON public.custom_field_definitions
    FOR DELETE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")

    op.execute("GRANT SELECT, INSERT, UPDATE ON public.custom_field_definitions TO assetflow_api")
    op.execute("GRANT SELECT ON public.custom_field_definitions TO assetflow_worker")
    op.execute("GRANT SELECT ON public.custom_field_definitions TO assetflow_readonly")
    op.execute("GRANT ALL ON public.custom_field_definitions TO assetflow_migrator")


def _create_manufacturers() -> None:
    """Manufacturers: flat reference data with fuzzy search (§B8.1)."""
    op.execute("""
CREATE TABLE public.manufacturers (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    code text NULL,
    name text NOT NULL,
    contact jsonb NOT NULL DEFAULT '{}'::jsonb,
    notes text NULL,
    status text NOT NULL DEFAULT 'active',
    version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT manufacturers_pkey PRIMARY KEY (id),
    CONSTRAINT uq_manufacturers__organization_id_id UNIQUE (organization_id, id),
    CONSTRAINT uq_manufacturers__organization_id_name UNIQUE (organization_id, name),
    CONSTRAINT fk_manufacturers__organization_id__organizations
        FOREIGN KEY (organization_id) REFERENCES public.organizations (id) ON DELETE RESTRICT,
    CONSTRAINT ck_manufacturers__contact_object CHECK (jsonb_typeof(contact) = 'object'),
    CONSTRAINT ck_manufacturers__status CHECK (status IN ('active', 'archived')),
    CONSTRAINT ck_manufacturers__version CHECK (version >= 1)
)
""")
    op.execute("ALTER TABLE public.manufacturers OWNER TO assetflow_migrator")
    op.execute("ALTER TABLE public.manufacturers ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.manufacturers FORCE ROW LEVEL SECURITY")
    op.execute("CREATE INDEX ix_manufacturers__organization_id ON public.manufacturers (organization_id)")
    op.execute(
        "CREATE INDEX ix_manufacturers__name_trgm ON public.manufacturers USING gin (name gin_trgm_ops)"
    )

    op.execute("""
CREATE POLICY rls_manufacturers_select ON public.manufacturers
    FOR SELECT
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY rls_manufacturers_insert ON public.manufacturers
    FOR INSERT
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY rls_manufacturers_update ON public.manufacturers
    FOR UPDATE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY rls_manufacturers_delete ON public.manufacturers
    FOR DELETE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")

    op.execute("GRANT SELECT, INSERT, UPDATE ON public.manufacturers TO assetflow_api")
    op.execute("GRANT SELECT ON public.manufacturers TO assetflow_worker")
    op.execute("GRANT SELECT ON public.manufacturers TO assetflow_readonly")
    op.execute("GRANT ALL ON public.manufacturers TO assetflow_migrator")


def _create_suppliers() -> None:
    """Suppliers: flat reference data with fuzzy search (§B8.1)."""
    op.execute("""
CREATE TABLE public.suppliers (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    code text NULL,
    name text NOT NULL,
    contact jsonb NOT NULL DEFAULT '{}'::jsonb,
    notes text NULL,
    status text NOT NULL DEFAULT 'active',
    version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT suppliers_pkey PRIMARY KEY (id),
    CONSTRAINT uq_suppliers__organization_id_id UNIQUE (organization_id, id),
    CONSTRAINT uq_suppliers__organization_id_name UNIQUE (organization_id, name),
    CONSTRAINT fk_suppliers__organization_id__organizations
        FOREIGN KEY (organization_id) REFERENCES public.organizations (id) ON DELETE RESTRICT,
    CONSTRAINT ck_suppliers__contact_object CHECK (jsonb_typeof(contact) = 'object'),
    CONSTRAINT ck_suppliers__status CHECK (status IN ('active', 'archived')),
    CONSTRAINT ck_suppliers__version CHECK (version >= 1)
)
""")
    op.execute("ALTER TABLE public.suppliers OWNER TO assetflow_migrator")
    op.execute("ALTER TABLE public.suppliers ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.suppliers FORCE ROW LEVEL SECURITY")
    op.execute("CREATE INDEX ix_suppliers__organization_id ON public.suppliers (organization_id)")
    op.execute("CREATE INDEX ix_suppliers__name_trgm ON public.suppliers USING gin (name gin_trgm_ops)")

    op.execute("""
CREATE POLICY rls_suppliers_select ON public.suppliers
    FOR SELECT
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY rls_suppliers_insert ON public.suppliers
    FOR INSERT
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY rls_suppliers_update ON public.suppliers
    FOR UPDATE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY rls_suppliers_delete ON public.suppliers
    FOR DELETE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")

    op.execute("GRANT SELECT, INSERT, UPDATE ON public.suppliers TO assetflow_api")
    op.execute("GRANT SELECT ON public.suppliers TO assetflow_worker")
    op.execute("GRANT SELECT ON public.suppliers TO assetflow_readonly")
    op.execute("GRANT ALL ON public.suppliers TO assetflow_migrator")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    _create_asset_categories()
    _create_custom_field_definitions()
    _create_manufacturers()
    _create_suppliers()


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.suppliers CASCADE")
    op.execute("DROP TABLE IF EXISTS public.manufacturers CASCADE")
    op.execute("DROP TABLE IF EXISTS public.custom_field_definitions CASCADE")
    op.execute("DROP TABLE IF EXISTS public.asset_categories CASCADE")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm CASCADE")
    op.execute("DROP EXTENSION IF EXISTS btree_gist CASCADE")
