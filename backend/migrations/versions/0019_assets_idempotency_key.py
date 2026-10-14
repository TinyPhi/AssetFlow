# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Idempotency-Key support for asset creation (§B4.5, §C1.5, M2.1-T5, P8-07).

Revision ID: 0019_assets_idempotency_key
Revises: 0018_organization_sequences
Create Date: 2026-10-05 00:00:19.000000

The plan (P8-07 step 3) requires `POST /api/v1/assets` to honor an `Idempotency-Key` header: a
retried request with the same key must return the same asset rather than creating a second one.
Not listed in the plan's own "Creates" (only `asset_saved_views` is), since no generic idempotency
store exists yet (M1.3 never built one) - the simplest correct option is a nullable column on
`assets` itself, scoped per organization like `tag`, rather than a new cross-module table for a
single call site.

`idempotency_key` is nullable (most writes, and every write from before this migration, have none)
and partial-unique per organization: two different assets in the same organization can never share
a non-null key, but any number of rows may have `NULL` (not a conflict, standard partial-index
behavior). The index is built `CREATE INDEX CONCURRENTLY` in an autocommit block (§C4.8 large-table
rule), consistent with every other index P8-03 added to this table.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0019_assets_idempotency_key"
down_revision: str | None = "0018_organization_sequences"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE public.assets ADD COLUMN idempotency_key text NULL")
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE UNIQUE INDEX CONCURRENTLY uq_assets__organization_id_idempotency_key "
            "ON public.assets (organization_id, idempotency_key) WHERE idempotency_key IS NOT NULL"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS uq_assets__organization_id_idempotency_key")
    op.execute("ALTER TABLE public.assets DROP COLUMN idempotency_key")
