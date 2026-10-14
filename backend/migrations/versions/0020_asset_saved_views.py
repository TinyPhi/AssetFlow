# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Per-member saved asset list views (§B8.1 "saved views", M2.1-T5, P8-07 step 7).

Revision ID: 0020_asset_saved_views
Revises: 0019_assets_idempotency_key
Create Date: 2026-10-05 00:00:20.000000

§B8.2 has no table for saved views; the plan adds `asset_saved_views`, owned by one member (sharing
a view between members is not in the master plan and is not built). A view stores only the list
query (filters), the sort and the visible columns; applying it re-runs the normal scoped list, so a
view never widens access. Same tenant-table shape as every other table: `organization_id NOT NULL`,
ENABLE and FORCE row level security, four fail-closed policies, an `organization_id`-first index.
The owning member is checked by the application on every read and write (a member sees only their
own views); the database guarantees the organization boundary and one name per member.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0020_asset_saved_views"
down_revision: str | None = "0019_assets_idempotency_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE public.asset_saved_views (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    member_id uuid NOT NULL,
    name text NOT NULL,
    query jsonb NOT NULL DEFAULT '{}'::jsonb,
    sort text NOT NULL DEFAULT '-created_at',
    columns text[] NOT NULL DEFAULT '{}',
    version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT asset_saved_views_pkey PRIMARY KEY (id),
    CONSTRAINT uq_asset_saved_views__organization_id_member_id_name
        UNIQUE (organization_id, member_id, name),
    CONSTRAINT fk_asset_saved_views__organization_id__organizations
        FOREIGN KEY (organization_id) REFERENCES public.organizations (id) ON DELETE RESTRICT,
    CONSTRAINT fk_asset_saved_views__member_id__members
        FOREIGN KEY (organization_id, member_id) REFERENCES public.members (organization_id, id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_asset_saved_views__name CHECK (length(btrim(name)) BETWEEN 1 AND 100),
    CONSTRAINT ck_asset_saved_views__query_object CHECK (jsonb_typeof(query) = 'object'),
    CONSTRAINT ck_asset_saved_views__version CHECK (version >= 1)
)
""")
    op.execute("ALTER TABLE public.asset_saved_views OWNER TO assetflow_migrator")
    op.execute("ALTER TABLE public.asset_saved_views ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.asset_saved_views FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE INDEX ix_asset_saved_views__organization_id_member_id "
        "ON public.asset_saved_views (organization_id, member_id)"
    )
    op.execute("""
CREATE POLICY rls_asset_saved_views_select ON public.asset_saved_views
    FOR SELECT
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY rls_asset_saved_views_insert ON public.asset_saved_views
    FOR INSERT
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY rls_asset_saved_views_update ON public.asset_saved_views
    FOR UPDATE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY rls_asset_saved_views_delete ON public.asset_saved_views
    FOR DELETE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    # A saved view is a personal preference, not business data: it may be hard-deleted (DELETE).
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON public.asset_saved_views TO assetflow_api")
    op.execute("GRANT SELECT ON public.asset_saved_views TO assetflow_worker")
    op.execute("GRANT SELECT ON public.asset_saved_views TO assetflow_readonly")
    op.execute("GRANT ALL ON public.asset_saved_views TO assetflow_migrator")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.asset_saved_views CASCADE")
