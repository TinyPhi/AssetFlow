# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Asset catalog, part b (master M2.1-T1, §B8.2, §B5.3, §C1.4, §C4.8, §C8.5).

Revision ID: 0017_assets_catalog
Revises: 0016_asset_catalog_reference
Create Date: 2026-10-04 00:00:17.000000

Second half of the asset catalog (part a, categories/custom fields/manufacturers/suppliers, is
P8-02):
  * assets: the catalog row (tag, name, category, model, manufacturer, serial number, owner org
    unit, location, holder, status, criticality, purchase date/cost, supplier, warranty end,
    custom and encrypted fields, notes).
  * asset_components: parent/child assets (a server and its disks), current attachment tracked by
    a partial unique index (`detached_at IS NULL`); cycle prevention is a service rule (P8-09).
  * meters, meter_readings: exist now so the M3.3 meter-triggered schedules need no schema change;
    no API in Phase 2.
  * v_asset_inventory: the read view the list and detail queries use (security_invoker).

Owner org unit path (§B8.2): `assets.owner_org_unit_path` is a denormalized copy of
`org_units.path`, kept in sync by two triggers so every future write path (service code, bulk
import, a future admin tool) gets it for free and scope filters stay index-friendly:
  * `trg_assets__owner_org_unit_path` (BEFORE INSERT OR UPDATE OF owner_org_unit_id ON assets)
    copies the current path from `org_units`.
  * `trg_org_units__asset_paths` (AFTER UPDATE OF path ON org_units) rewrites the
    `owner_org_unit_path` of every asset owned by that unit when it moves. Unlike the P5-04
    org-unit-move repository method's own cascade to descendant org_units (which splices with
    `subpath`/`nlevel` because a descendant's path is *longer* than the moved node's), an asset's
    `owner_org_unit_path` is always an *exact* copy of its owning unit's path (never deeper), so
    this trigger matches by plain equality and replaces the whole path - simpler, and it sidesteps
    ltree's `subpath(path, offset)` raising "invalid positions" when `offset = nlevel(path)`, which
    is exactly the case an equality match would always hit. Both functions are `SECURITY INVOKER`
    (the default for a PL/pgSQL function with no `SECURITY DEFINER` clause), so RLS still applies
    to the `org_units`/`assets` reads and writes they do.

Every table has:
  * organization_id uuid NOT NULL referencing public.organizations(id)
  * ENABLE ROW LEVEL SECURITY and FORCE ROW LEVEL SECURITY
  * Four fail-closed policies for SELECT, INSERT, UPDATE, DELETE, named rls_<table>_<op>
  * An organization_id-first index or unique constraint
  * A `version` column for optimistic concurrency, except `meter_readings`: a reading is an
    immutable fact once recorded (the service never updates one, only inserts), so it has no
    `version` and no `updated_at` - just `created_at`. This mirrors the plan's own column list for
    `meter_readings` (no `version`/`updated_at` listed there) and `audit_events`' append-only
    convention.

No `updated_at` trigger: as in 0016, no table anywhere in this schema has one (a `fn_set_updated_at`
trigger function does not exist in the codebase); these tables follow the same existing convention
(plain application UPDATE) rather than introducing one single-handedly.

`status` and `criticality` on `assets` are plain `text` with **no** CHECK constraint restricting
their values (unlike `asset_categories.status`/`custom_field_definitions.status`, which are
platform-fixed `active`/`archived`): per §B8.1 "Statuses come from config", the set of valid asset
statuses and criticality levels is domain-template data (P8-01), validated by the service layer
(P8-04/P8-08), not hardcoded here - hardcoding them in a CHECK would bake one domain's vocabulary
into the schema.

Large-table rule (§C4.8): `assets` indexes are created `CREATE INDEX CONCURRENTLY` inside an
Alembic autocommit block (`op.get_context().autocommit_block()`), since CONCURRENTLY cannot run
inside the migration's own transaction.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0017_assets_catalog"
down_revision: str | None = "0016_asset_catalog_reference"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_assets_table() -> None:
    op.execute("""
CREATE TABLE public.assets (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    tag text NOT NULL,
    name text NOT NULL,
    category_id uuid NOT NULL,
    model text NULL,
    manufacturer_id uuid NULL,
    supplier_id uuid NULL,
    serial_number text NULL,
    owner_org_unit_id uuid NOT NULL,
    owner_org_unit_path ltree NOT NULL,
    location_id uuid NULL,
    holder_member_id uuid NULL,
    holder_team_id uuid NULL,
    holder_location_id uuid NULL,
    status text NOT NULL DEFAULT 'active',
    criticality text NULL,
    purchase_date date NULL,
    purchase_cost numeric(14, 2) NULL,
    warranty_end date NULL,
    custom_fields jsonb NOT NULL DEFAULT '{}'::jsonb,
    encrypted_fields jsonb NOT NULL DEFAULT '{}'::jsonb,
    notes text NULL,
    version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT assets_pkey PRIMARY KEY (id),
    CONSTRAINT uq_assets__organization_id_id UNIQUE (organization_id, id),
    CONSTRAINT uq_assets__organization_id_tag UNIQUE (organization_id, tag),
    CONSTRAINT fk_assets__organization_id__organizations
        FOREIGN KEY (organization_id) REFERENCES public.organizations (id) ON DELETE RESTRICT,
    CONSTRAINT fk_assets__category_id__asset_categories
        FOREIGN KEY (organization_id, category_id)
            REFERENCES public.asset_categories (organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_assets__manufacturer_id__manufacturers
        FOREIGN KEY (organization_id, manufacturer_id)
            REFERENCES public.manufacturers (organization_id, id) ON DELETE SET NULL,
    CONSTRAINT fk_assets__supplier_id__suppliers
        FOREIGN KEY (organization_id, supplier_id)
            REFERENCES public.suppliers (organization_id, id) ON DELETE SET NULL,
    CONSTRAINT fk_assets__owner_org_unit_id__org_units
        FOREIGN KEY (organization_id, owner_org_unit_id)
            REFERENCES public.org_units (organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_assets__location_id__locations
        FOREIGN KEY (organization_id, location_id)
            REFERENCES public.locations (organization_id, id) ON DELETE SET NULL,
    CONSTRAINT fk_assets__holder_member_id__members
        FOREIGN KEY (organization_id, holder_member_id)
            REFERENCES public.members (organization_id, id) ON DELETE SET NULL,
    CONSTRAINT fk_assets__holder_team_id__teams
        FOREIGN KEY (organization_id, holder_team_id)
            REFERENCES public.teams (organization_id, id) ON DELETE SET NULL,
    CONSTRAINT fk_assets__holder_location_id__locations
        FOREIGN KEY (organization_id, holder_location_id)
            REFERENCES public.locations (organization_id, id) ON DELETE SET NULL,
    CONSTRAINT ck_assets__one_holder CHECK (
        num_nonnulls(holder_member_id, holder_team_id, holder_location_id) <= 1
    ),
    CONSTRAINT ck_assets__custom_fields_object CHECK (jsonb_typeof(custom_fields) = 'object'),
    CONSTRAINT ck_assets__encrypted_fields_object CHECK (jsonb_typeof(encrypted_fields) = 'object'),
    CONSTRAINT ck_assets__version CHECK (version >= 1)
)
""")
    op.execute("ALTER TABLE public.assets OWNER TO assetflow_migrator")
    op.execute("ALTER TABLE public.assets ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.assets FORCE ROW LEVEL SECURITY")

    op.execute("""
CREATE POLICY rls_assets_select ON public.assets
    FOR SELECT
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY rls_assets_insert ON public.assets
    FOR INSERT
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY rls_assets_update ON public.assets
    FOR UPDATE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY rls_assets_delete ON public.assets
    FOR DELETE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")

    op.execute("GRANT SELECT, INSERT, UPDATE ON public.assets TO assetflow_api")
    op.execute("GRANT SELECT ON public.assets TO assetflow_worker")
    op.execute("GRANT SELECT ON public.assets TO assetflow_readonly")
    op.execute("GRANT ALL ON public.assets TO assetflow_migrator")


def _create_assets_indexes() -> None:
    """All `assets` indexes CONCURRENTLY, in an autocommit block (§C4.8 large-table rule)."""
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY ix_assets__organization_id_created_at_id "
            "ON public.assets (organization_id, created_at, id)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY ix_assets__organization_id_status "
            "ON public.assets (organization_id, status)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY ix_assets__organization_id_category_id "
            "ON public.assets (organization_id, category_id)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY ix_assets__organization_id_location_id "
            "ON public.assets (organization_id, location_id)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY ix_assets__organization_id_warranty_end "
            "ON public.assets (organization_id, warranty_end)"
        )
        # Scope branches (§B5.3): org unit path (GiST, via btree_gist so organization_id can lead),
        # holder team id, holder member id.
        op.execute(
            "CREATE INDEX CONCURRENTLY ix_assets__organization_id_owner_org_unit_path_gist "
            "ON public.assets USING gist (organization_id, owner_org_unit_path)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY ix_assets__organization_id_holder_team_id "
            "ON public.assets (organization_id, holder_team_id)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY ix_assets__organization_id_holder_member_id "
            "ON public.assets (organization_id, holder_member_id)"
        )
        # Fuzzy search (pg_trgm, §B8.1).
        op.execute(
            "CREATE INDEX CONCURRENTLY ix_assets__tag_trgm ON public.assets USING gin (tag gin_trgm_ops)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY ix_assets__name_trgm ON public.assets USING gin (name gin_trgm_ops)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY ix_assets__serial_number_trgm "
            "ON public.assets USING gin (serial_number gin_trgm_ops)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY ix_assets__model_trgm ON public.assets USING gin (model gin_trgm_ops)"
        )
        # Custom field filter; no index on encrypted_fields (never searched, §B8.1).
        op.execute(
            "CREATE INDEX CONCURRENTLY ix_assets__custom_fields_gin "
            "ON public.assets USING gin (custom_fields jsonb_path_ops)"
        )


def _create_owner_org_unit_path_triggers() -> None:
    """Keep `assets.owner_org_unit_path` in sync with `org_units.path` (§B8.2)."""
    op.execute("""
CREATE FUNCTION public.fn_assets__set_owner_org_unit_path() RETURNS trigger
    LANGUAGE plpgsql
    SECURITY INVOKER
    AS $$
BEGIN
    SELECT path INTO STRICT NEW.owner_org_unit_path
    FROM public.org_units
    WHERE organization_id = NEW.organization_id AND id = NEW.owner_org_unit_id;
    RETURN NEW;
END;
$$
""")
    op.execute("""
CREATE TRIGGER trg_assets__owner_org_unit_path
    BEFORE INSERT OR UPDATE OF owner_org_unit_id ON public.assets
    FOR EACH ROW
    EXECUTE FUNCTION public.fn_assets__set_owner_org_unit_path()
""")

    # An asset's owner_org_unit_path is always an exact copy of its owning unit's path (the
    # BEFORE trigger above never copies a descendant's path onto an asset), so a moved unit's
    # assets are matched and rewritten by plain equality - no subpath/nlevel splicing needed here
    # (unlike org_units' own move, which does splice because a descendant org_unit's path is
    # *longer* than the moved ancestor's path). ltree's single-argument subpath(path, offset)
    # raises "invalid positions" when offset = nlevel(path), i.e. exactly the case an equality
    # match on owner_org_unit_path would always hit, so that formula does not apply here.
    op.execute("""
CREATE FUNCTION public.fn_org_units__asset_paths() RETURNS trigger
    LANGUAGE plpgsql
    SECURITY INVOKER
    AS $$
BEGIN
    UPDATE public.assets
    SET owner_org_unit_path = NEW.path,
        updated_at = now()
    WHERE organization_id = NEW.organization_id
      AND owner_org_unit_path = OLD.path;
    RETURN NEW;
END;
$$
""")
    op.execute("""
CREATE TRIGGER trg_org_units__asset_paths
    AFTER UPDATE OF path ON public.org_units
    FOR EACH ROW
    WHEN (OLD.path IS DISTINCT FROM NEW.path)
    EXECUTE FUNCTION public.fn_org_units__asset_paths()
""")


def _create_asset_components() -> None:
    op.execute("""
CREATE TABLE public.asset_components (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    parent_asset_id uuid NOT NULL,
    child_asset_id uuid NOT NULL,
    attached_at timestamptz NOT NULL DEFAULT now(),
    detached_at timestamptz NULL,
    version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT asset_components_pkey PRIMARY KEY (id),
    CONSTRAINT uq_asset_components__organization_id_id UNIQUE (organization_id, id),
    CONSTRAINT fk_asset_components__organization_id__organizations
        FOREIGN KEY (organization_id) REFERENCES public.organizations (id) ON DELETE RESTRICT,
    CONSTRAINT fk_asset_components__parent_asset_id__assets
        FOREIGN KEY (organization_id, parent_asset_id)
            REFERENCES public.assets (organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_asset_components__child_asset_id__assets
        FOREIGN KEY (organization_id, child_asset_id)
            REFERENCES public.assets (organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_asset_components__not_self CHECK (parent_asset_id != child_asset_id),
    CONSTRAINT ck_asset_components__version CHECK (version >= 1)
)
""")
    op.execute("ALTER TABLE public.asset_components OWNER TO assetflow_migrator")
    op.execute("ALTER TABLE public.asset_components ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.asset_components FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE INDEX ix_asset_components__organization_id_parent_asset_id "
        "ON public.asset_components (organization_id, parent_asset_id)"
    )
    op.execute(
        "CREATE INDEX ix_asset_components__organization_id_child_asset_id "
        "ON public.asset_components (organization_id, child_asset_id)"
    )
    # A child has at most one *current* parent (§B8.1 "components: parent/child assets").
    op.execute(
        "CREATE UNIQUE INDEX uq_asset_components__organization_id_child_asset_id "
        "ON public.asset_components (organization_id, child_asset_id) WHERE detached_at IS NULL"
    )

    op.execute("""
CREATE POLICY rls_asset_components_select ON public.asset_components
    FOR SELECT
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY rls_asset_components_insert ON public.asset_components
    FOR INSERT
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY rls_asset_components_update ON public.asset_components
    FOR UPDATE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY rls_asset_components_delete ON public.asset_components
    FOR DELETE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")

    op.execute("GRANT SELECT, INSERT, UPDATE ON public.asset_components TO assetflow_api")
    op.execute("GRANT SELECT ON public.asset_components TO assetflow_worker")
    op.execute("GRANT SELECT ON public.asset_components TO assetflow_readonly")
    op.execute("GRANT ALL ON public.asset_components TO assetflow_migrator")


def _create_meters() -> None:
    op.execute("""
CREATE TABLE public.meters (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    asset_id uuid NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    unit text NOT NULL,
    is_cumulative boolean NOT NULL DEFAULT true,
    status text NOT NULL DEFAULT 'active',
    version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT meters_pkey PRIMARY KEY (id),
    CONSTRAINT uq_meters__organization_id_id UNIQUE (organization_id, id),
    CONSTRAINT uq_meters__organization_id_asset_id_code UNIQUE (organization_id, asset_id, code),
    CONSTRAINT fk_meters__organization_id__organizations
        FOREIGN KEY (organization_id) REFERENCES public.organizations (id) ON DELETE RESTRICT,
    CONSTRAINT fk_meters__asset_id__assets
        FOREIGN KEY (organization_id, asset_id)
            REFERENCES public.assets (organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_meters__status CHECK (status IN ('active', 'archived')),
    CONSTRAINT ck_meters__version CHECK (version >= 1)
)
""")
    op.execute("ALTER TABLE public.meters OWNER TO assetflow_migrator")
    op.execute("ALTER TABLE public.meters ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.meters FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE INDEX ix_meters__organization_id_asset_id ON public.meters (organization_id, asset_id)"
    )

    op.execute("""
CREATE POLICY rls_meters_select ON public.meters
    FOR SELECT
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY rls_meters_insert ON public.meters
    FOR INSERT
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY rls_meters_update ON public.meters
    FOR UPDATE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY rls_meters_delete ON public.meters
    FOR DELETE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")

    op.execute("GRANT SELECT, INSERT, UPDATE ON public.meters TO assetflow_api")
    op.execute("GRANT SELECT ON public.meters TO assetflow_worker")
    op.execute("GRANT SELECT ON public.meters TO assetflow_readonly")
    op.execute("GRANT ALL ON public.meters TO assetflow_migrator")


def _create_meter_readings() -> None:
    op.execute("""
CREATE TABLE public.meter_readings (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    meter_id uuid NOT NULL,
    value numeric NOT NULL,
    read_at timestamptz NOT NULL,
    recorded_by_member_id uuid NULL,
    source text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT meter_readings_pkey PRIMARY KEY (id),
    CONSTRAINT uq_meter_readings__organization_id_id UNIQUE (organization_id, id),
    CONSTRAINT fk_meter_readings__organization_id__organizations
        FOREIGN KEY (organization_id) REFERENCES public.organizations (id) ON DELETE RESTRICT,
    CONSTRAINT fk_meter_readings__meter_id__meters
        FOREIGN KEY (organization_id, meter_id)
            REFERENCES public.meters (organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_meter_readings__recorded_by_member_id__members
        FOREIGN KEY (organization_id, recorded_by_member_id)
            REFERENCES public.members (organization_id, id) ON DELETE SET NULL,
    CONSTRAINT ck_meter_readings__source CHECK (source IN ('manual', 'work_order', 'import'))
)
""")
    op.execute("ALTER TABLE public.meter_readings OWNER TO assetflow_migrator")
    op.execute("ALTER TABLE public.meter_readings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.meter_readings FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE INDEX ix_meter_readings__organization_id_meter_id_read_at "
        "ON public.meter_readings (organization_id, meter_id, read_at DESC)"
    )

    op.execute("""
CREATE POLICY rls_meter_readings_select ON public.meter_readings
    FOR SELECT
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY rls_meter_readings_insert ON public.meter_readings
    FOR INSERT
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY rls_meter_readings_update ON public.meter_readings
    FOR UPDATE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY rls_meter_readings_delete ON public.meter_readings
    FOR DELETE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")

    # Readings are facts: INSERT only for api and worker, no UPDATE, no DELETE.
    op.execute("GRANT SELECT, INSERT ON public.meter_readings TO assetflow_api")
    op.execute("GRANT SELECT, INSERT ON public.meter_readings TO assetflow_worker")
    op.execute("GRANT SELECT ON public.meter_readings TO assetflow_readonly")
    op.execute("GRANT ALL ON public.meter_readings TO assetflow_migrator")


def _create_views() -> None:
    """`v_asset_inventory`: the read view the list and detail queries use (security_invoker)."""
    op.execute("""
CREATE VIEW public.v_asset_inventory WITH (security_invoker = true) AS
SELECT
    a.id,
    a.organization_id,
    a.tag,
    a.name,
    a.category_id,
    cat.name AS category_name,
    a.model,
    a.manufacturer_id,
    mfr.name AS manufacturer_name,
    a.supplier_id,
    sup.name AS supplier_name,
    a.serial_number,
    a.owner_org_unit_id,
    ou.name AS owner_org_unit_name,
    a.owner_org_unit_path,
    a.location_id,
    loc.name AS location_name,
    CASE
        WHEN a.holder_member_id IS NOT NULL THEN 'member'
        WHEN a.holder_team_id IS NOT NULL THEN 'team'
        WHEN a.holder_location_id IS NOT NULL THEN 'location'
    END AS holder_type,
    COALESCE(a.holder_member_id, a.holder_team_id, a.holder_location_id) AS holder_id,
    COALESCE(hm.display_name, ht.name, hl.name) AS holder_display_name,
    a.status,
    a.criticality,
    a.purchase_date,
    a.purchase_cost,
    a.warranty_end,
    a.custom_fields,
    a.notes,
    a.version,
    a.created_at,
    a.updated_at
FROM public.assets a
JOIN public.asset_categories cat ON cat.organization_id = a.organization_id AND cat.id = a.category_id
LEFT JOIN public.manufacturers mfr
    ON mfr.organization_id = a.organization_id AND mfr.id = a.manufacturer_id
LEFT JOIN public.suppliers sup ON sup.organization_id = a.organization_id AND sup.id = a.supplier_id
JOIN public.org_units ou ON ou.organization_id = a.organization_id AND ou.id = a.owner_org_unit_id
LEFT JOIN public.locations loc ON loc.organization_id = a.organization_id AND loc.id = a.location_id
LEFT JOIN public.members hm ON hm.organization_id = a.organization_id AND hm.id = a.holder_member_id
LEFT JOIN public.teams ht ON ht.organization_id = a.organization_id AND ht.id = a.holder_team_id
LEFT JOIN public.locations hl ON hl.organization_id = a.organization_id AND hl.id = a.holder_location_id
""")
    op.execute("GRANT SELECT ON public.v_asset_inventory TO assetflow_api")
    op.execute("GRANT SELECT ON public.v_asset_inventory TO assetflow_worker")
    op.execute("GRANT SELECT ON public.v_asset_inventory TO assetflow_readonly")


def upgrade() -> None:
    _create_assets_table()
    _create_asset_components()
    _create_meters()
    _create_meter_readings()
    _create_owner_org_unit_path_triggers()
    _create_views()
    _create_assets_indexes()


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS public.v_asset_inventory CASCADE")
    op.execute("DROP TRIGGER IF EXISTS trg_org_units__asset_paths ON public.org_units")
    op.execute("DROP FUNCTION IF EXISTS public.fn_org_units__asset_paths()")
    op.execute("DROP TABLE IF EXISTS public.meter_readings CASCADE")
    op.execute("DROP TABLE IF EXISTS public.meters CASCADE")
    op.execute("DROP TABLE IF EXISTS public.asset_components CASCADE")
    op.execute("DROP TABLE IF EXISTS public.assets CASCADE")
    op.execute("DROP FUNCTION IF EXISTS public.fn_assets__set_owner_org_unit_path()")
