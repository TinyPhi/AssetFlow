# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Notification tables: channel installations, in-app inbox, delivery log, preferences (§B6.3, M1.5-T3/T6/T7).

Revision ID: 0010_notification_tables
Revises: 0009_worker_support
Create Date: 2026-10-04 00:00:10.000000

Creates:
  * notification_channels (per-organization channel installations: settings, kill switch, an
    OpenBao reference for credentials, never a credential value)
  * notifications (the in-app inbox: one row per member per notice, read/unread, retention)
  * notification_deliveries (the delivery log: one row per attempt, any channel, pseudonymous
    target only - never an email address, phone number or name)
  * notification_preferences (per member, per event type, per channel)

Every table has:
  * organization_id uuid NOT NULL referencing public.organizations(id)
  * ENABLE ROW LEVEL SECURITY and FORCE ROW LEVEL SECURITY
  * Four fail-closed policies for SELECT, INSERT, UPDATE, DELETE
  * An organization_id-first index

No version column and no updated_at trigger: neither exists anywhere in the current schema
(outbox, organization_modules, members all set updated_at with a plain application UPDATE), so
these tables follow the same convention rather than introducing a new one.

channel_key is a free text column, not a CHECK constraint: a third-party channel (master §B6.3
rule 9, "first-party only in 1.0... third-party channel packages are allowed through entry
points") must be installable without a migration.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010_notification_tables"
down_revision: str | None = "0009_worker_support"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_notification_channels() -> None:
    """Per-organization channel installations (§B6.3)."""
    op.execute("""
CREATE TABLE public.notification_channels (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    channel_key text NOT NULL,
    display_name text NOT NULL,
    settings jsonb NOT NULL DEFAULT '{}'::jsonb,
    secret_ref text NULL,
    enabled boolean NOT NULL DEFAULT true,
    allowed_hosts text[] NOT NULL DEFAULT '{}',
    allow_personal_data boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT notification_channels_pkey PRIMARY KEY (id),
    CONSTRAINT uq_notification_channels__org_id_id UNIQUE (organization_id, id),
    CONSTRAINT uq_notification_channels__organization_id_channel_key UNIQUE (organization_id, channel_key),
    CONSTRAINT fk_notification_channels__organization_id__organizations
        FOREIGN KEY (organization_id) REFERENCES public.organizations (id) ON DELETE RESTRICT,
    CONSTRAINT ck_notification_channels__settings_object CHECK (jsonb_typeof(settings) = 'object')
)
""")
    op.execute("ALTER TABLE public.notification_channels OWNER TO assetflow_migrator")
    op.execute("ALTER TABLE public.notification_channels ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.notification_channels FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE INDEX ix_notification_channels__organization_id "
        "ON public.notification_channels (organization_id)"
    )

    op.execute("""
CREATE POLICY notification_channels_select ON public.notification_channels
    FOR SELECT
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY notification_channels_insert ON public.notification_channels
    FOR INSERT
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY notification_channels_update ON public.notification_channels
    FOR UPDATE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY notification_channels_delete ON public.notification_channels
    FOR DELETE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")

    op.execute("GRANT SELECT, INSERT, UPDATE ON public.notification_channels TO assetflow_api")
    op.execute("GRANT SELECT ON public.notification_channels TO assetflow_worker")
    op.execute("GRANT SELECT ON public.notification_channels TO assetflow_readonly")
    op.execute("GRANT ALL ON public.notification_channels TO assetflow_migrator")


def _create_notifications() -> None:
    """The in-app inbox: one row per member per notice (§B6.3)."""
    op.execute("""
CREATE TABLE public.notifications (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    member_id uuid NOT NULL,
    event_type text NOT NULL,
    event_id uuid NOT NULL,
    template_key text NOT NULL,
    title_key text NOT NULL,
    body text NOT NULL,
    link_entity_type text NULL,
    link_entity_id uuid NULL,
    read_at timestamptz NULL,
    idempotency_key text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT notifications_pkey PRIMARY KEY (id),
    CONSTRAINT uq_notifications__org_id_id UNIQUE (organization_id, id),
    CONSTRAINT uq_notifications__organization_id_idempotency_key UNIQUE (organization_id, idempotency_key),
    CONSTRAINT fk_notifications__organization_id__organizations
        FOREIGN KEY (organization_id) REFERENCES public.organizations (id) ON DELETE RESTRICT,
    CONSTRAINT fk_notifications__member_id__members
        FOREIGN KEY (organization_id, member_id)
            REFERENCES public.members (organization_id, id) ON DELETE CASCADE
)
""")
    op.execute("ALTER TABLE public.notifications OWNER TO assetflow_migrator")
    op.execute("ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.notifications FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE INDEX ix_notifications__organization_id_member_id_updated_at "
        "ON public.notifications (organization_id, member_id, updated_at DESC)"
    )
    op.execute(
        "CREATE INDEX ix_notifications__organization_id_member_id_unread "
        "ON public.notifications (organization_id, member_id) WHERE read_at IS NULL"
    )

    op.execute("""
CREATE POLICY notifications_select ON public.notifications
    FOR SELECT
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY notifications_insert ON public.notifications
    FOR INSERT
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY notifications_update ON public.notifications
    FOR UPDATE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY notifications_delete ON public.notifications
    FOR DELETE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")

    op.execute("GRANT SELECT, INSERT, UPDATE ON public.notifications TO assetflow_api")
    op.execute("GRANT SELECT, INSERT, DELETE ON public.notifications TO assetflow_worker")
    op.execute("GRANT SELECT ON public.notifications TO assetflow_readonly")
    op.execute("GRANT ALL ON public.notifications TO assetflow_migrator")


def _create_notification_deliveries() -> None:
    """The delivery log: one row per attempt, any channel (§B6.3)."""
    op.execute("""
CREATE TABLE public.notification_deliveries (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    channel_id uuid NOT NULL,
    channel_key text NOT NULL,
    event_id uuid NOT NULL,
    recipient_member_id uuid NULL,
    target text NOT NULL,
    idempotency_key text NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    attempts integer NOT NULL DEFAULT 0,
    latency_ms integer NULL,
    error_code text NULL,
    next_retry_at timestamptz NULL,
    claimed_by text NULL,
    claimed_at timestamptz NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT notification_deliveries_pkey PRIMARY KEY (id),
    CONSTRAINT uq_notification_deliveries__org_id_id UNIQUE (organization_id, id),
    CONSTRAINT uq_notification_deliveries__organization_id_idempotency_key
        UNIQUE (organization_id, idempotency_key),
    CONSTRAINT fk_notification_deliveries__organization_id__organizations
        FOREIGN KEY (organization_id) REFERENCES public.organizations (id) ON DELETE RESTRICT,
    CONSTRAINT fk_notification_deliveries__channel_id__notification_channels
        FOREIGN KEY (organization_id, channel_id)
            REFERENCES public.notification_channels (organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_notification_deliveries__recipient_member_id__members
        FOREIGN KEY (organization_id, recipient_member_id)
            REFERENCES public.members (organization_id, id) ON DELETE SET NULL,
    CONSTRAINT ck_notification_deliveries__status
        CHECK (status IN ('pending', 'sending', 'sent', 'failed', 'dead_lettered', 'skipped')),
    CONSTRAINT ck_notification_deliveries__attempts CHECK (attempts >= 0)
)
""")
    op.execute("ALTER TABLE public.notification_deliveries OWNER TO assetflow_migrator")
    op.execute("ALTER TABLE public.notification_deliveries ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.notification_deliveries FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE INDEX ix_notification_deliveries__organization_id "
        "ON public.notification_deliveries (organization_id)"
    )
    op.execute(
        "CREATE INDEX ix_notification_deliveries__organization_id_status_next_retry "
        "ON public.notification_deliveries (organization_id, status, next_retry_at)"
    )

    op.execute("""
CREATE POLICY notification_deliveries_select ON public.notification_deliveries
    FOR SELECT
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY notification_deliveries_insert ON public.notification_deliveries
    FOR INSERT
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY notification_deliveries_update ON public.notification_deliveries
    FOR UPDATE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY notification_deliveries_delete ON public.notification_deliveries
    FOR DELETE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")

    op.execute("GRANT SELECT ON public.notification_deliveries TO assetflow_api")
    op.execute("GRANT SELECT, INSERT, UPDATE ON public.notification_deliveries TO assetflow_worker")
    op.execute("GRANT SELECT ON public.notification_deliveries TO assetflow_readonly")
    op.execute("GRANT ALL ON public.notification_deliveries TO assetflow_migrator")


def _create_notification_preferences() -> None:
    """Per member, per event type, per channel (§B6.3)."""
    op.execute("""
CREATE TABLE public.notification_preferences (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    member_id uuid NOT NULL,
    event_type text NOT NULL,
    channel_key text NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT notification_preferences_pkey PRIMARY KEY (id),
    CONSTRAINT uq_notification_preferences__org_id_id UNIQUE (organization_id, id),
    CONSTRAINT uq_notification_preferences__org_id_member_event_channel
        UNIQUE (organization_id, member_id, event_type, channel_key),
    CONSTRAINT fk_notification_preferences__organization_id__organizations
        FOREIGN KEY (organization_id) REFERENCES public.organizations (id) ON DELETE RESTRICT,
    CONSTRAINT fk_notification_preferences__member_id__members
        FOREIGN KEY (organization_id, member_id)
            REFERENCES public.members (organization_id, id) ON DELETE CASCADE
)
""")
    op.execute("ALTER TABLE public.notification_preferences OWNER TO assetflow_migrator")
    op.execute("ALTER TABLE public.notification_preferences ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.notification_preferences FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE INDEX ix_notification_preferences__organization_id_member_id "
        "ON public.notification_preferences (organization_id, member_id)"
    )

    op.execute("""
CREATE POLICY notification_preferences_select ON public.notification_preferences
    FOR SELECT
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY notification_preferences_insert ON public.notification_preferences
    FOR INSERT
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY notification_preferences_update ON public.notification_preferences
    FOR UPDATE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY notification_preferences_delete ON public.notification_preferences
    FOR DELETE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON public.notification_preferences TO assetflow_api")
    op.execute("GRANT SELECT ON public.notification_preferences TO assetflow_worker")
    op.execute("GRANT SELECT ON public.notification_preferences TO assetflow_readonly")
    op.execute("GRANT ALL ON public.notification_preferences TO assetflow_migrator")


def upgrade() -> None:
    _create_notification_channels()
    _create_notifications()
    _create_notification_deliveries()
    _create_notification_preferences()


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.notification_preferences CASCADE")
    op.execute("DROP TABLE IF EXISTS public.notification_deliveries CASCADE")
    op.execute("DROP TABLE IF EXISTS public.notifications CASCADE")
    op.execute("DROP TABLE IF EXISTS public.notification_channels CASCADE")
