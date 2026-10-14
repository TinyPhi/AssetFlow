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

A key belongs to the member who sent it (PR #348/#352 review): `idempotency_member_id` records the
creator, and uniqueness is per (organization, member, key), so one member's key never replays
another member's asset, and the same key from a different member is simply a new request. Both
columns are set together or not at all, and the key is 1-255 characters, so an over-long key is a
clean refusal, never a B-tree index-row overflow. No FK on the member: members are archived, not
deleted, and the column only scopes replay lookups.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0019_assets_idempotency_key"
down_revision: str | None = "0018_organization_sequences"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
ALTER TABLE public.assets
    ADD COLUMN idempotency_key text NULL,
    ADD COLUMN idempotency_member_id uuid NULL,
    ADD CONSTRAINT ck_assets__idempotency_key_length
        CHECK (idempotency_key IS NULL OR char_length(idempotency_key) BETWEEN 1 AND 255),
    ADD CONSTRAINT ck_assets__idempotency_key_member
        CHECK ((idempotency_key IS NULL) = (idempotency_member_id IS NULL))
""")
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE UNIQUE INDEX CONCURRENTLY uq_assets__organization_id_idempotency_member_id_key "
            "ON public.assets (organization_id, idempotency_member_id, idempotency_key) "
            "WHERE idempotency_key IS NOT NULL"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS uq_assets__organization_id_idempotency_member_id_key")
    op.execute("""
ALTER TABLE public.assets
    DROP CONSTRAINT ck_assets__idempotency_key_member,
    DROP CONSTRAINT ck_assets__idempotency_key_length,
    DROP COLUMN idempotency_member_id,
    DROP COLUMN idempotency_key
""")
