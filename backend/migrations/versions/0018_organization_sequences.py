# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Per-organization number sequences (master M1.3-T3, M2.1-T3, §B7.3 `assets.tag`, §B8.1).

Revision ID: 0018_organization_sequences
Revises: 0017_assets_catalog
Create Date: 2026-10-04 00:00:18.000000

M1.3-T3 asked for per-organization number sequences; neither `backend/app/core/ids.py` (UUIDv7
generation only) nor any earlier migration created a counter table, so this is the first use of
one (P8-05). A plain PostgreSQL `SEQUENCE` is not an option here: it is a single global counter
shared by every organization, which leaks the existence and rate of one organization's inserts to
every other (§C5.4 cross-tenant leakage).

`organization_sequences` holds one row per `(organization_id, sequence_key)`; asset tag generation
uses the key `asset_tag:<prefix>` so each tag prefix (the template's own prefix, or a category's
override) counts on its own, per organization, starting at 1. `next_value` is the number the *next*
caller receives; `UPDATE ... SET next_value = next_value + 1 ... RETURNING next_value - 1` takes the
row's lock for the statement's duration, so two concurrent callers are serialized and never receive
the same number (gaps from a rolled-back caller are accepted - uniqueness matters, not continuity).
A future consumer with its own counter (for example a work-order number) reuses this same table with
its own `sequence_key`, so it is not named `asset_sequences`.

Same tenant-table shape as every other table in this schema: `organization_id NOT NULL`, ENABLE and
FORCE row level security, four fail-closed policies named `rls_<table>_<op>`, an
`organization_id`-first unique constraint and index. No `updated_at` trigger: as 0016 and 0017
already documented, no `fn_set_updated_at` trigger function exists anywhere in this codebase (every
table from 0001 sets `updated_at` by application UPDATE); this table follows the same convention
rather than introducing the trigger unilaterally for one table.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0018_organization_sequences"
down_revision: str | None = "0017_assets_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE public.organization_sequences (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    sequence_key text NOT NULL,
    next_value bigint NOT NULL DEFAULT 1,
    version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT organization_sequences_pkey PRIMARY KEY (id),
    CONSTRAINT uq_organization_sequences__organization_id_sequence_key
        UNIQUE (organization_id, sequence_key),
    CONSTRAINT fk_organization_sequences__organization_id__organizations
        FOREIGN KEY (organization_id) REFERENCES public.organizations (id) ON DELETE RESTRICT,
    CONSTRAINT ck_organization_sequences__sequence_key_format
        CHECK (sequence_key ~ '^[a-z][a-z0-9_]*:[A-Za-z0-9]+$'),
    CONSTRAINT ck_organization_sequences__next_value CHECK (next_value >= 1),
    CONSTRAINT ck_organization_sequences__version CHECK (version >= 1)
)
""")
    op.execute("ALTER TABLE public.organization_sequences OWNER TO assetflow_migrator")
    op.execute("ALTER TABLE public.organization_sequences ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.organization_sequences FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE INDEX ix_organization_sequences__organization_id "
        "ON public.organization_sequences (organization_id)"
    )

    op.execute("""
CREATE POLICY rls_organization_sequences_select ON public.organization_sequences
    FOR SELECT
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY rls_organization_sequences_insert ON public.organization_sequences
    FOR INSERT
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY rls_organization_sequences_update ON public.organization_sequences
    FOR UPDATE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY rls_organization_sequences_delete ON public.organization_sequences
    FOR DELETE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")

    # No DELETE grant: a counter is never deleted by the application (§B14.1 archive-by-status
    # convention extends here to "never remove a counter row").
    op.execute("GRANT SELECT, INSERT, UPDATE ON public.organization_sequences TO assetflow_api")
    op.execute("GRANT SELECT ON public.organization_sequences TO assetflow_worker")
    op.execute("GRANT SELECT ON public.organization_sequences TO assetflow_readonly")
    op.execute("GRANT ALL ON public.organization_sequences TO assetflow_migrator")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.organization_sequences CASCADE")
