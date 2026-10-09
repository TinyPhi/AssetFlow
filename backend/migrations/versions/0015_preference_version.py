# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Optimistic concurrency for member notification preferences (§B10, M1.5-T7).

Revision ID: 0015_preference_version
Revises: 0014_channel_admin_support
Create Date: 2026-10-04 00:00:15.000000

A member's preference matrix can be edited from two screens at once; each stored cell carries a
version so a change made from a stale copy is a 409, not a silent overwrite. 0010 left the column out
because nothing edited a row yet.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015_preference_version"
down_revision: str | None = "0014_channel_admin_support"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE public.notification_preferences ADD COLUMN version integer NOT NULL DEFAULT 1")


def downgrade() -> None:
    op.execute("ALTER TABLE public.notification_preferences DROP COLUMN version")
