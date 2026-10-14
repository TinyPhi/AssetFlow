# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Organization modules table (§B5.2, §B5.9, §B10, §C4.8).

Revision ID: 0004_org_modules
Revises: 0003_org_access
Create Date: 2026-10-01 00:00:04.000000

Creates the module installation table:
  * organization_modules (tracks installed product areas: assets, maintenance)

Every table has:
  * organization_id uuid NOT NULL referencing public.organizations(id)
  * ENABLE ROW LEVEL SECURITY and FORCE ROW LEVEL SECURITY
  * Four fail-closed policies for SELECT, INSERT, UPDATE, DELETE
  * Indexes whose first column is organization_id
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004_org_modules"
down_revision: str | None = "0003_org_access"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE public.organization_modules (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    module_key text NOT NULL,
    template_key text NOT NULL,
    status text NOT NULL DEFAULT 'installed',
    installed_at timestamptz NOT NULL DEFAULT now(),
    installed_by uuid NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT organization_modules_pkey PRIMARY KEY (id),
    CONSTRAINT uq_organization_modules__org_id_id UNIQUE (organization_id, id),
    CONSTRAINT uq_organization_modules__organization_id_module_key UNIQUE (organization_id, module_key),
    CONSTRAINT fk_organization_modules__organization_id__organizations
        FOREIGN KEY (organization_id) REFERENCES public.organizations (id) ON DELETE RESTRICT,
    CONSTRAINT fk_organization_modules__installed_by__members
        FOREIGN KEY (organization_id, installed_by)
            REFERENCES public.members (organization_id, id) ON DELETE SET NULL,
    CONSTRAINT ck_organization_modules__status CHECK (status IN ('installed', 'uninstalled')),
    CONSTRAINT ck_organization_modules__module_key CHECK (module_key IN ('assets', 'maintenance'))
)
""")
    op.execute("ALTER TABLE public.organization_modules OWNER TO assetflow_migrator")
    op.execute("ALTER TABLE public.organization_modules ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.organization_modules FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE INDEX ix_organization_modules__organization_id "
        "ON public.organization_modules (organization_id)"
    )

    op.execute("""
CREATE POLICY organization_modules_select ON public.organization_modules
    FOR SELECT
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY organization_modules_insert ON public.organization_modules
    FOR INSERT
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY organization_modules_update ON public.organization_modules
    FOR UPDATE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY organization_modules_delete ON public.organization_modules
    FOR DELETE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON public.organization_modules TO assetflow_api")
    op.execute("GRANT SELECT ON public.organization_modules TO assetflow_worker")
    op.execute("GRANT SELECT ON public.organization_modules TO assetflow_readonly")
    op.execute("GRANT ALL ON public.organization_modules TO assetflow_migrator")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.organization_modules CASCADE")
