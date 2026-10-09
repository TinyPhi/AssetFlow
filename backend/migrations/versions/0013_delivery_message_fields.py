# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""What the notification sender needs to render a pending delivery later (§B6.3, M1.5-T6).

Revision ID: 0013_delivery_message_fields
Revises: 0012_domain_key_lookup
Create Date: 2026-10-04 00:00:13.000000

A pending delivery is sent by the worker some time after the subscriber planned it, outside any
transaction (§B10), so the row itself must carry what the channel needs to render: the template,
the event type, and only the event fields that template declares (payload minimization, §B6.3
rule 3 - never the whole event payload). `entity_type` / `entity_id` name the record the event is
about, so a dead-lettered delivery can leave its note on that record (§B6.3 rule 5).

All five columns are nullable or defaulted: existing rows (in-app deliveries, written already
sent) have no use for them. The worker role already holds INSERT and UPDATE on this table (0010).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013_delivery_message_fields"
down_revision: str | None = "0012_domain_key_lookup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE public.notification_deliveries ADD COLUMN template_key text NULL")
    op.execute("ALTER TABLE public.notification_deliveries ADD COLUMN event_type text NULL")
    op.execute("ALTER TABLE public.notification_deliveries ADD COLUMN entity_type text NULL")
    op.execute("ALTER TABLE public.notification_deliveries ADD COLUMN entity_id uuid NULL")
    op.execute(
        "ALTER TABLE public.notification_deliveries "
        "ADD COLUMN message_data jsonb NOT NULL DEFAULT '{}'::jsonb"
    )
    op.execute(
        "ALTER TABLE public.notification_deliveries "
        "ADD CONSTRAINT ck_notification_deliveries__message_data_object "
        "CHECK (jsonb_typeof(message_data) = 'object')"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE public.notification_deliveries "
        "DROP CONSTRAINT ck_notification_deliveries__message_data_object"
    )
    op.execute("ALTER TABLE public.notification_deliveries DROP COLUMN message_data")
    op.execute("ALTER TABLE public.notification_deliveries DROP COLUMN entity_id")
    op.execute("ALTER TABLE public.notification_deliveries DROP COLUMN entity_type")
    op.execute("ALTER TABLE public.notification_deliveries DROP COLUMN event_type")
    op.execute("ALTER TABLE public.notification_deliveries DROP COLUMN template_key")
