# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Organization structure tables: calendars, org units tree, locations tree, and teams (§B5.2, §B10, §C4.8).

Revision ID: 0002_org_structure
Revises: 0001_organizations
Create Date: 2026-10-01 00:00:02.000000

Creates the tenant hierarchy tables:
  * working_calendars (operating hours, holidays)
  * org_units (department tree using ltree materialized paths)
  * locations (facility tree using ltree materialized paths)
  * teams (collaborative groups referencing org units and calendars)

Every table has:
  * organization_id uuid NOT NULL referencing public.organizations(id)
  * ENABLE ROW LEVEL SECURITY and FORCE ROW LEVEL SECURITY
  * Four fail-closed policies for SELECT, INSERT, UPDATE, DELETE
  * Indexes whose first column is organization_id
  * Self-referencing composite foreign keys guaranteeing child nodes stay in the parent's organization
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_org_structure"
down_revision: str | None = "0001_organizations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_working_calendars() -> None:
    """Working_calendars."""
    op.execute("""
CREATE TABLE public.working_calendars (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    name text NOT NULL,
    timezone text NOT NULL DEFAULT 'UTC',
    weekly_hours jsonb NOT NULL DEFAULT '{}'::jsonb,
    holidays date[] NOT NULL DEFAULT '{}'::date[],
    version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT working_calendars_pkey PRIMARY KEY (id),
    CONSTRAINT uq_working_calendars__org_id_id UNIQUE (organization_id, id),
    CONSTRAINT uq_working_calendars__org_id_name UNIQUE (organization_id, name),
    CONSTRAINT fk_working_calendars__organization_id__organizations
        FOREIGN KEY (organization_id) REFERENCES public.organizations (id) ON DELETE RESTRICT,
    CONSTRAINT ck_working_calendars__weekly_hours_object CHECK (jsonb_typeof(weekly_hours) = 'object'),
    CONSTRAINT ck_working_calendars__version CHECK (version >= 1)
)
""")
    op.execute("ALTER TABLE public.working_calendars OWNER TO assetflow_migrator")
    op.execute("ALTER TABLE public.working_calendars ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.working_calendars FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE INDEX ix_working_calendars__organization_id ON public.working_calendars (organization_id)"
    )

    op.execute("""
CREATE POLICY working_calendars_select ON public.working_calendars
    FOR SELECT
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY working_calendars_insert ON public.working_calendars
    FOR INSERT
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY working_calendars_update ON public.working_calendars
    FOR UPDATE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY working_calendars_delete ON public.working_calendars
    FOR DELETE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON public.working_calendars TO assetflow_api")
    op.execute("GRANT SELECT ON public.working_calendars TO assetflow_worker")
    op.execute("GRANT SELECT ON public.working_calendars TO assetflow_readonly")
    op.execute("GRANT ALL ON public.working_calendars TO assetflow_migrator")


def _create_org_units() -> None:
    """Org_units."""
    op.execute("""
CREATE TABLE public.org_units (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    parent_id uuid NULL,
    path ltree NOT NULL,
    type text NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    manager_member_id uuid NULL,
    status text NOT NULL DEFAULT 'active',
    version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT org_units_pkey PRIMARY KEY (id),
    CONSTRAINT uq_org_units__org_id_id UNIQUE (organization_id, id),
    CONSTRAINT uq_org_units__org_id_code UNIQUE (organization_id, code),
    CONSTRAINT fk_org_units__organization_id__organizations
        FOREIGN KEY (organization_id) REFERENCES public.organizations (id) ON DELETE RESTRICT,
    CONSTRAINT fk_org_units__parent_id__org_units
        FOREIGN KEY (organization_id, parent_id)
            REFERENCES public.org_units (organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_org_units__status CHECK (status IN ('active', 'archived')),
    CONSTRAINT ck_org_units__version CHECK (version >= 1)
)
""")
    op.execute("ALTER TABLE public.org_units OWNER TO assetflow_migrator")
    op.execute("ALTER TABLE public.org_units ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.org_units FORCE ROW LEVEL SECURITY")
    op.execute("CREATE INDEX ix_org_units__organization_id ON public.org_units (organization_id)")
    op.execute(
        "CREATE INDEX ix_org_units__organization_id_parent ON public.org_units (organization_id, parent_id)"
    )
    op.execute("CREATE INDEX ix_org_units__path_gist ON public.org_units USING gist (path)")

    op.execute("""
CREATE POLICY org_units_select ON public.org_units
    FOR SELECT
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY org_units_insert ON public.org_units
    FOR INSERT
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY org_units_update ON public.org_units
    FOR UPDATE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY org_units_delete ON public.org_units
    FOR DELETE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON public.org_units TO assetflow_api")
    op.execute("GRANT SELECT ON public.org_units TO assetflow_worker")
    op.execute("GRANT SELECT ON public.org_units TO assetflow_readonly")
    op.execute("GRANT ALL ON public.org_units TO assetflow_migrator")


def _create_locations() -> None:
    """Locations."""
    op.execute("""
CREATE TABLE public.locations (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    parent_id uuid NULL,
    path ltree NOT NULL,
    type text NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    address jsonb NOT NULL DEFAULT '{}'::jsonb,
    version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT locations_pkey PRIMARY KEY (id),
    CONSTRAINT uq_locations__org_id_id UNIQUE (organization_id, id),
    CONSTRAINT uq_locations__org_id_code UNIQUE (organization_id, code),
    CONSTRAINT fk_locations__organization_id__organizations
        FOREIGN KEY (organization_id) REFERENCES public.organizations (id) ON DELETE RESTRICT,
    CONSTRAINT fk_locations__parent_id__locations
        FOREIGN KEY (organization_id, parent_id)
            REFERENCES public.locations (organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_locations__address_object CHECK (jsonb_typeof(address) = 'object'),
    CONSTRAINT ck_locations__version CHECK (version >= 1)
)
""")
    op.execute("ALTER TABLE public.locations OWNER TO assetflow_migrator")
    op.execute("ALTER TABLE public.locations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.locations FORCE ROW LEVEL SECURITY")
    op.execute("CREATE INDEX ix_locations__organization_id ON public.locations (organization_id)")
    op.execute(
        "CREATE INDEX ix_locations__organization_id_parent ON public.locations (organization_id, parent_id)"
    )
    op.execute("CREATE INDEX ix_locations__path_gist ON public.locations USING gist (path)")

    op.execute("""
CREATE POLICY locations_select ON public.locations
    FOR SELECT
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY locations_insert ON public.locations
    FOR INSERT
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY locations_update ON public.locations
    FOR UPDATE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY locations_delete ON public.locations
    FOR DELETE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON public.locations TO assetflow_api")
    op.execute("GRANT SELECT ON public.locations TO assetflow_worker")
    op.execute("GRANT SELECT ON public.locations TO assetflow_readonly")
    op.execute("GRANT ALL ON public.locations TO assetflow_migrator")


def _create_teams() -> None:
    """Teams."""
    op.execute("""
CREATE TABLE public.teams (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    owning_org_unit_id uuid NULL,
    type text NOT NULL,
    skills text[] NOT NULL DEFAULT '{}'::text[],
    working_calendar_id uuid NULL,
    status text NOT NULL DEFAULT 'active',
    version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT teams_pkey PRIMARY KEY (id),
    CONSTRAINT uq_teams__org_id_id UNIQUE (organization_id, id),
    CONSTRAINT uq_teams__org_id_code UNIQUE (organization_id, code),
    CONSTRAINT fk_teams__organization_id__organizations
        FOREIGN KEY (organization_id) REFERENCES public.organizations (id) ON DELETE RESTRICT,
    CONSTRAINT fk_teams__owning_org_unit_id__org_units
        FOREIGN KEY (organization_id, owning_org_unit_id)
            REFERENCES public.org_units (organization_id, id) ON DELETE SET NULL,
    CONSTRAINT fk_teams__working_calendar_id__working_calendars
        FOREIGN KEY (organization_id, working_calendar_id)
            REFERENCES public.working_calendars (organization_id, id) ON DELETE SET NULL,
    CONSTRAINT ck_teams__status CHECK (status IN ('active', 'archived')),
    CONSTRAINT ck_teams__version CHECK (version >= 1)
)
""")
    op.execute("ALTER TABLE public.teams OWNER TO assetflow_migrator")
    op.execute("ALTER TABLE public.teams ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.teams FORCE ROW LEVEL SECURITY")
    op.execute("CREATE INDEX ix_teams__organization_id ON public.teams (organization_id)")
    op.execute(
        "CREATE INDEX ix_teams__organization_id_owning_org_unit "
        "ON public.teams (organization_id, owning_org_unit_id)"
    )

    op.execute("""
CREATE POLICY teams_select ON public.teams
    FOR SELECT
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY teams_insert ON public.teams
    FOR INSERT
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY teams_update ON public.teams
    FOR UPDATE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY teams_delete ON public.teams
    FOR DELETE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON public.teams TO assetflow_api")
    op.execute("GRANT SELECT ON public.teams TO assetflow_worker")
    op.execute("GRANT SELECT ON public.teams TO assetflow_readonly")
    op.execute("GRANT ALL ON public.teams TO assetflow_migrator")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS ltree")

    _create_working_calendars()
    _create_org_units()
    _create_locations()
    _create_teams()


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.teams CASCADE")
    op.execute("DROP TABLE IF EXISTS public.locations CASCADE")
    op.execute("DROP TABLE IF EXISTS public.org_units CASCADE")
    op.execute("DROP TABLE IF EXISTS public.working_calendars CASCADE")
    op.execute("DROP EXTENSION IF EXISTS ltree CASCADE")
