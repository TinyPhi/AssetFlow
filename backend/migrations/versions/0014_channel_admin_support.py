# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Support for the channel installations API and delivery log (§B6.3, §B10, M1.5-T6).

Revision ID: 0014_channel_admin_support
Revises: 0013_delivery_message_fields
Create Date: 2026-10-04 00:00:14.000000

* `notification_channels.version` - optimistic concurrency like every other admin-edited entity
  (§B10): an update carries the version it read, a mismatch is a 409. 0010 left it out because no
  code edited a row yet.
* `notification_channels.secret_fields_set` - the names of the secret fields that have a stored
  value. The credential itself lives only in OpenBao and the api role cannot read it back, so this
  is how the API reports "set / not set" per secret field (never a value, never a reference).
* The api role may update the retry state of a delivery (and nothing else on it), which is what
  re-queuing a dead-lettered delivery is. Column-level, so it cannot rewrite who or what a delivery
  was for.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014_channel_admin_support"
down_revision: str | None = "0013_delivery_message_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RETRY_COLUMNS = "status, attempts, error_code, next_retry_at, claimed_by, claimed_at, updated_at"


def upgrade() -> None:
    op.execute("ALTER TABLE public.notification_channels ADD COLUMN version integer NOT NULL DEFAULT 1")
    op.execute(
        "ALTER TABLE public.notification_channels ADD COLUMN secret_fields_set text[] NOT NULL DEFAULT '{}'"
    )
    op.execute(f"GRANT UPDATE ({_RETRY_COLUMNS}) ON public.notification_deliveries TO assetflow_api")


def downgrade() -> None:
    op.execute(f"REVOKE UPDATE ({_RETRY_COLUMNS}) ON public.notification_deliveries FROM assetflow_api")
    op.execute("ALTER TABLE public.notification_channels DROP COLUMN secret_fields_set")
    op.execute("ALTER TABLE public.notification_channels DROP COLUMN version")
