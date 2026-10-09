# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Worker grant for auto-installing the `inapp` channel (§B6.3, M1.5-T3).

Revision ID: 0011_notification_worker_grants
Revises: 0010_notification_tables
Create Date: 2026-10-04 00:00:11.000000

`inapp` needs no settings and no admin setup (§B6.3: "always installed"), so the worker installs
its one `notification_channels` row itself, idempotently, the first time it has an in-app notice
to send - 0010 granted the worker role only SELECT on that table (installations are otherwise an
admin-only, API-role concern), so this grants it INSERT too, narrowly, for that one row shape.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011_notification_worker_grants"
down_revision: str | None = "0010_notification_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("GRANT INSERT ON public.notification_channels TO assetflow_worker")


def downgrade() -> None:
    op.execute("REVOKE INSERT ON public.notification_channels FROM assetflow_worker")
