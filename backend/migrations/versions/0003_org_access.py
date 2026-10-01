# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Organization access tables: members, member org units, team members, and role grants (§B5.2, §B10, §C4.8).

Revision ID: 0003_org_access
Revises: 0002_org_structure
Create Date: 2026-10-01 00:00:03.000000

Creates access and membership tables:
  * members (provisioned users, status lifecycle, IdP subject mapping)
  * member_org_units (multi-unit assignment: primary / secondary)
  * team_members (time-bounded membership and roles in teams)
  * role_grants (scoped permissions at organization, org unit, or team level)
  * Circular reference resolution: links org_units.manager_member_id to members(id)

Every table has:
  * organization_id uuid NOT NULL referencing public.organizations(id)
  * ENABLE ROW LEVEL SECURITY and FORCE ROW LEVEL SECURITY
  * Four fail-closed policies for SELECT, INSERT, UPDATE, DELETE
  * Indexes whose first column is organization_id
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_org_access"
down_revision: str | None = "0002_org_structure"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_members() -> None:
    """Members."""
    op.execute("""
CREATE TABLE public.members (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    idp_subject text NOT NULL,
    email text NOT NULL,
    display_name text NOT NULL,
    member_number text NULL,
    primary_org_unit_id uuid NULL,
    job_title text NULL,
    status text NOT NULL DEFAULT 'invited',
    version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT members_pkey PRIMARY KEY (id),
    CONSTRAINT uq_members__org_id_id UNIQUE (organization_id, id),
    CONSTRAINT uq_members__organization_id_idp_subject UNIQUE (organization_id, idp_subject),
    CONSTRAINT uq_members__organization_id_email UNIQUE (organization_id, email),
    CONSTRAINT fk_members__organization_id__organizations
        FOREIGN KEY (organization_id) REFERENCES public.organizations (id) ON DELETE RESTRICT,
    CONSTRAINT fk_members__primary_org_unit_id__org_units
        FOREIGN KEY (organization_id, primary_org_unit_id)
            REFERENCES public.org_units (organization_id, id) ON DELETE SET NULL,
    CONSTRAINT ck_members__status CHECK (status IN ('invited', 'active', 'suspended', 'left')),
    CONSTRAINT ck_members__version CHECK (version >= 1)
)
""")
    op.execute("ALTER TABLE public.members OWNER TO assetflow_migrator")
    op.execute("ALTER TABLE public.members ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.members FORCE ROW LEVEL SECURITY")
    op.execute("CREATE INDEX ix_members__organization_id ON public.members (organization_id)")
    op.execute("CREATE INDEX ix_members__organization_id_email ON public.members (organization_id, email)")
    op.execute(
        "CREATE INDEX ix_members__organization_id_primary_org_unit "
        "ON public.members (organization_id, primary_org_unit_id)"
    )

    op.execute("""
CREATE POLICY members_select ON public.members
    FOR SELECT
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY members_insert ON public.members
    FOR INSERT
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY members_update ON public.members
    FOR UPDATE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY members_delete ON public.members
    FOR DELETE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON public.members TO assetflow_api")
    op.execute("GRANT SELECT, UPDATE ON public.members TO assetflow_worker")
    op.execute("GRANT SELECT ON public.members TO assetflow_readonly")
    op.execute("GRANT ALL ON public.members TO assetflow_migrator")


def _add_circular_foreign_keys() -> None:
    """Circular FK: org_units.manager_member_id -> members(id)."""
    op.execute("""
ALTER TABLE public.org_units
    ADD CONSTRAINT fk_org_units__manager_member_id__members
    FOREIGN KEY (organization_id, manager_member_id)
    REFERENCES public.members (organization_id, id)
    ON DELETE SET NULL
""")


def _create_member_org_units() -> None:
    """Member_org_units."""
    op.execute("""
CREATE TABLE public.member_org_units (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    member_id uuid NOT NULL,
    org_unit_id uuid NOT NULL,
    relation text NOT NULL DEFAULT 'secondary',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT member_org_units_pkey PRIMARY KEY (id),
    CONSTRAINT uq_member_org_units__org_id_id UNIQUE (organization_id, id),
    CONSTRAINT uq_member_org_units__org_id_member_org_unit UNIQUE (organization_id, member_id, org_unit_id),
    CONSTRAINT fk_member_org_units__organization_id__organizations
        FOREIGN KEY (organization_id) REFERENCES public.organizations (id) ON DELETE RESTRICT,
    CONSTRAINT fk_member_org_units__member_id__members
        FOREIGN KEY (organization_id, member_id)
            REFERENCES public.members (organization_id, id) ON DELETE CASCADE,
    CONSTRAINT fk_member_org_units__org_unit_id__org_units
        FOREIGN KEY (organization_id, org_unit_id)
            REFERENCES public.org_units (organization_id, id) ON DELETE CASCADE,
    CONSTRAINT ck_member_org_units__relation CHECK (relation IN ('primary', 'secondary'))
)
""")
    op.execute("ALTER TABLE public.member_org_units OWNER TO assetflow_migrator")
    op.execute("ALTER TABLE public.member_org_units ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.member_org_units FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE INDEX ix_member_org_units__organization_id ON public.member_org_units (organization_id)"
    )
    op.execute(
        "CREATE INDEX ix_member_org_units__organization_id_member "
        "ON public.member_org_units (organization_id, member_id)"
    )
    op.execute(
        "CREATE INDEX ix_member_org_units__organization_id_org_unit "
        "ON public.member_org_units (organization_id, org_unit_id)"
    )

    op.execute("""
CREATE POLICY member_org_units_select ON public.member_org_units
    FOR SELECT
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY member_org_units_insert ON public.member_org_units
    FOR INSERT
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY member_org_units_update ON public.member_org_units
    FOR UPDATE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY member_org_units_delete ON public.member_org_units
    FOR DELETE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON public.member_org_units TO assetflow_api")
    op.execute("GRANT SELECT ON public.member_org_units TO assetflow_worker")
    op.execute("GRANT SELECT ON public.member_org_units TO assetflow_readonly")
    op.execute("GRANT ALL ON public.member_org_units TO assetflow_migrator")


def _create_team_members() -> None:
    """Team_members."""
    op.execute("""
CREATE TABLE public.team_members (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    team_id uuid NOT NULL,
    member_id uuid NOT NULL,
    team_role text NOT NULL DEFAULT 'member',
    valid_from timestamptz NOT NULL DEFAULT now(),
    valid_to timestamptz NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT team_members_pkey PRIMARY KEY (id),
    CONSTRAINT uq_team_members__org_id_id UNIQUE (organization_id, id),
    CONSTRAINT uq_team_members__org_id_team_member UNIQUE (organization_id, team_id, member_id),
    CONSTRAINT fk_team_members__organization_id__organizations
        FOREIGN KEY (organization_id) REFERENCES public.organizations (id) ON DELETE RESTRICT,
    CONSTRAINT fk_team_members__team_id__teams
        FOREIGN KEY (organization_id, team_id)
            REFERENCES public.teams (organization_id, id) ON DELETE CASCADE,
    CONSTRAINT fk_team_members__member_id__members
        FOREIGN KEY (organization_id, member_id)
            REFERENCES public.members (organization_id, id) ON DELETE CASCADE,
    CONSTRAINT ck_team_members__team_role CHECK (team_role IN ('lead', 'member')),
    CONSTRAINT ck_team_members__dates CHECK (valid_to IS NULL OR valid_to >= valid_from)
)
""")
    op.execute("ALTER TABLE public.team_members OWNER TO assetflow_migrator")
    op.execute("ALTER TABLE public.team_members ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.team_members FORCE ROW LEVEL SECURITY")
    op.execute("CREATE INDEX ix_team_members__organization_id ON public.team_members (organization_id)")
    op.execute(
        "CREATE INDEX ix_team_members__organization_id_team ON public.team_members (organization_id, team_id)"
    )
    op.execute(
        "CREATE INDEX ix_team_members__organization_id_member "
        "ON public.team_members (organization_id, member_id)"
    )

    op.execute("""
CREATE POLICY team_members_select ON public.team_members
    FOR SELECT
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY team_members_insert ON public.team_members
    FOR INSERT
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY team_members_update ON public.team_members
    FOR UPDATE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY team_members_delete ON public.team_members
    FOR DELETE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON public.team_members TO assetflow_api")
    op.execute("GRANT SELECT ON public.team_members TO assetflow_worker")
    op.execute("GRANT SELECT ON public.team_members TO assetflow_readonly")
    op.execute("GRANT ALL ON public.team_members TO assetflow_migrator")


def _create_role_grants() -> None:
    """Role_grants."""
    op.execute("""
CREATE TABLE public.role_grants (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    member_id uuid NULL,
    team_id uuid NULL,
    role_key text NOT NULL,
    scope_type text NOT NULL,
    scope_id uuid NULL,
    granted_by uuid NULL,
    expires_at timestamptz NULL,
    source text NOT NULL DEFAULT 'manual',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT role_grants_pkey PRIMARY KEY (id),
    CONSTRAINT uq_role_grants__org_id_id UNIQUE (organization_id, id),
    CONSTRAINT fk_role_grants__organization_id__organizations
        FOREIGN KEY (organization_id) REFERENCES public.organizations (id) ON DELETE RESTRICT,
    CONSTRAINT fk_role_grants__member_id__members
        FOREIGN KEY (organization_id, member_id)
            REFERENCES public.members (organization_id, id) ON DELETE CASCADE,
    CONSTRAINT fk_role_grants__team_id__teams
        FOREIGN KEY (organization_id, team_id)
            REFERENCES public.teams (organization_id, id) ON DELETE CASCADE,
    CONSTRAINT fk_role_grants__granted_by__members
        FOREIGN KEY (organization_id, granted_by)
            REFERENCES public.members (organization_id, id) ON DELETE SET NULL,
    CONSTRAINT ck_role_grants__target
        CHECK ((member_id IS NOT NULL AND team_id IS NULL) OR (member_id IS NULL AND team_id IS NOT NULL)),
    CONSTRAINT ck_role_grants__scope_type
        CHECK (scope_type IN ('organization', 'org_unit', 'team')),
    CONSTRAINT ck_role_grants__source
        CHECK (source IN ('idp', 'manual')),
    CONSTRAINT ck_role_grants__scope_id
        CHECK ((scope_type = 'organization' AND scope_id IS NULL)
            OR (scope_type IN ('org_unit', 'team') AND scope_id IS NOT NULL))
)
""")
    op.execute("ALTER TABLE public.role_grants OWNER TO assetflow_migrator")
    op.execute("ALTER TABLE public.role_grants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.role_grants FORCE ROW LEVEL SECURITY")
    op.execute("CREATE INDEX ix_role_grants__organization_id ON public.role_grants (organization_id)")
    op.execute(
        "CREATE INDEX ix_role_grants__organization_id_member "
        "ON public.role_grants (organization_id, member_id)"
    )
    op.execute(
        "CREATE INDEX ix_role_grants__organization_id_team ON public.role_grants (organization_id, team_id)"
    )
    op.execute(
        "CREATE INDEX ix_role_grants__organization_id_role_key "
        "ON public.role_grants (organization_id, role_key)"
    )

    op.execute("""
CREATE POLICY role_grants_select ON public.role_grants
    FOR SELECT
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY role_grants_insert ON public.role_grants
    FOR INSERT
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY role_grants_update ON public.role_grants
    FOR UPDATE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY role_grants_delete ON public.role_grants
    FOR DELETE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON public.role_grants TO assetflow_api")
    op.execute("GRANT SELECT ON public.role_grants TO assetflow_worker")
    op.execute("GRANT SELECT ON public.role_grants TO assetflow_readonly")
    op.execute("GRANT ALL ON public.role_grants TO assetflow_migrator")


def upgrade() -> None:
    _create_members()
    _add_circular_foreign_keys()
    _create_member_org_units()
    _create_team_members()
    _create_role_grants()


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.role_grants CASCADE")
    op.execute("DROP TABLE IF EXISTS public.team_members CASCADE")
    op.execute("DROP TABLE IF EXISTS public.member_org_units CASCADE")
    op.execute(
        "ALTER TABLE IF EXISTS public.org_units "
        "DROP CONSTRAINT IF EXISTS fk_org_units__manager_member_id__members"
    )
    op.execute("DROP TABLE IF EXISTS public.members CASCADE")
