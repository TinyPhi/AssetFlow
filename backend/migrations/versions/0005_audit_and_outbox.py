# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Audit and transactional outbox tables (§B5.2, §B9.3, §B10, §C4.8).

Revision ID: 0005_audit_and_outbox
Revises: 0004_org_modules
Create Date: 2026-10-01 00:00:05.000000

Creates event and audit tables:
  * audit_events (insert-only audit log of state mutations, actor, role, and scope)
  * outbox (transactional event queue with claiming and retry tracking)
  * processed_events (consumer idempotency records)

Every table has:
  * organization_id uuid NOT NULL referencing public.organizations(id)
  * ENABLE ROW LEVEL SECURITY and FORCE ROW LEVEL SECURITY
  * Four fail-closed policies for SELECT, INSERT, UPDATE, DELETE
  * Indexes whose first column is organization_id
  * outbox carries worker claim policies for un-scoped queue consumption (§B9.3)
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005_audit_and_outbox"
down_revision: str | None = "0004_org_modules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. audit_events
    op.execute("""
CREATE TABLE public.audit_events (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    actor_member_id uuid NULL,
    action text NOT NULL,
    entity_type text NOT NULL,
    entity_id uuid NOT NULL,
    role_used text NULL,
    scope_type text NULL,
    scope_id uuid NULL,
    request_id text NULL,
    client_id text NULL,
    before_state jsonb NULL,
    after_state jsonb NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT audit_events_pkey PRIMARY KEY (id, created_at),
    CONSTRAINT uq_audit_events__org_id_id UNIQUE (organization_id, id, created_at),
    CONSTRAINT fk_audit_events__organization_id__organizations
        FOREIGN KEY (organization_id) REFERENCES public.organizations (id) ON DELETE RESTRICT
) PARTITION BY RANGE (created_at)
""")
    # No foreign key to members: actor_member_id is a pseudonymous id that must survive the member,
    # and an ON DELETE action would rewrite insert-only rows (§B10, §1590).
    # Monthly partitions are created ahead by the audit housekeeping (P5-08); rows without a
    # monthly partition land in DEFAULT, which the housekeeping keeps empty and alerts on.
    op.execute("CREATE TABLE public.audit_events_default PARTITION OF public.audit_events DEFAULT")
    op.execute("ALTER TABLE public.audit_events_default OWNER TO assetflow_migrator")
    # Reads and writes go through audit_events and its policies; direct access to a partition has
    # no policy and no grant, so it is denied (fail-closed).
    op.execute("ALTER TABLE public.audit_events_default ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.audit_events_default FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.audit_events OWNER TO assetflow_migrator")
    op.execute("ALTER TABLE public.audit_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.audit_events FORCE ROW LEVEL SECURITY")
    op.execute("CREATE INDEX ix_audit_events__organization_id ON public.audit_events (organization_id)")
    op.execute(
        "CREATE INDEX ix_audit_events__organization_id_created "
        "ON public.audit_events (organization_id, created_at)"
    )
    op.execute(
        "CREATE INDEX ix_audit_events__organization_id_entity "
        "ON public.audit_events (organization_id, entity_type, entity_id)"
    )

    op.execute("""
CREATE POLICY audit_events_select ON public.audit_events
    FOR SELECT
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY audit_events_insert ON public.audit_events
    FOR INSERT
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY audit_events_update ON public.audit_events
    FOR UPDATE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY audit_events_delete ON public.audit_events
    FOR DELETE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")

    # Application roles have insert-only access; no UPDATE or DELETE (§B10)
    op.execute("GRANT SELECT, INSERT ON public.audit_events TO assetflow_api")
    op.execute("GRANT SELECT, INSERT ON public.audit_events TO assetflow_worker")
    op.execute("GRANT SELECT ON public.audit_events TO assetflow_readonly")
    op.execute("GRANT ALL ON public.audit_events TO assetflow_migrator")

    # 2. outbox
    op.execute("""
CREATE TABLE public.outbox (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    event_type text NOT NULL,
    aggregate_type text NOT NULL,
    aggregate_id uuid NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    claimed_by text NULL,
    claimed_at timestamptz NULL,
    processed_at timestamptz NULL,
    attempts integer NOT NULL DEFAULT 0,
    last_error text NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT outbox_pkey PRIMARY KEY (id),
    CONSTRAINT uq_outbox__org_id_id UNIQUE (organization_id, id),
    CONSTRAINT fk_outbox__organization_id__organizations
        FOREIGN KEY (organization_id) REFERENCES public.organizations (id) ON DELETE RESTRICT,
    CONSTRAINT ck_outbox__payload_object CHECK (jsonb_typeof(payload) = 'object'),
    CONSTRAINT ck_outbox__attempts CHECK (attempts >= 0)
)
""")
    op.execute("ALTER TABLE public.outbox OWNER TO assetflow_migrator")
    op.execute("ALTER TABLE public.outbox ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.outbox FORCE ROW LEVEL SECURITY")
    op.execute("CREATE INDEX ix_outbox__organization_id ON public.outbox (organization_id)")
    op.execute(
        "CREATE INDEX ix_outbox__organization_id_processed ON public.outbox (organization_id, processed_at)"
    )
    op.execute("CREATE INDEX ix_outbox__claimed_by ON public.outbox (claimed_by)")

    # Organization-scoped policies
    op.execute("""
CREATE POLICY outbox_select ON public.outbox
    FOR SELECT
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY outbox_insert ON public.outbox
    FOR INSERT
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY outbox_update ON public.outbox
    FOR UPDATE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY outbox_delete ON public.outbox
    FOR DELETE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")

    # Worker claim policies (§B9.3 exception)
    op.execute("""
CREATE POLICY outbox_worker_claim_select ON public.outbox
    FOR SELECT
    TO assetflow_worker
    USING (true)
""")
    op.execute("""
CREATE POLICY outbox_worker_claim_update ON public.outbox
    FOR UPDATE
    TO assetflow_worker
    USING (true)
    WITH CHECK (true)
""")

    op.execute("GRANT SELECT, INSERT ON public.outbox TO assetflow_api")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON public.outbox TO assetflow_worker")
    op.execute("GRANT SELECT ON public.outbox TO assetflow_readonly")
    op.execute("GRANT ALL ON public.outbox TO assetflow_migrator")

    # 3. processed_events
    op.execute("""
CREATE TABLE public.processed_events (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    consumer_name text NOT NULL,
    event_id uuid NOT NULL,
    processed_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT processed_events_pkey PRIMARY KEY (id),
    CONSTRAINT uq_processed_events__org_id_id UNIQUE (organization_id, id),
    CONSTRAINT uq_processed_events__org_id_consumer_event UNIQUE (organization_id, consumer_name, event_id),
    CONSTRAINT fk_processed_events__organization_id__organizations
        FOREIGN KEY (organization_id) REFERENCES public.organizations (id) ON DELETE RESTRICT
)
""")
    op.execute("ALTER TABLE public.processed_events OWNER TO assetflow_migrator")
    op.execute("ALTER TABLE public.processed_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.processed_events FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE INDEX ix_processed_events__organization_id ON public.processed_events (organization_id)"
    )

    op.execute("""
CREATE POLICY processed_events_select ON public.processed_events
    FOR SELECT
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY processed_events_insert ON public.processed_events
    FOR INSERT
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY processed_events_update ON public.processed_events
    FOR UPDATE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")
    op.execute("""
CREATE POLICY processed_events_delete ON public.processed_events
    FOR DELETE
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
""")

    op.execute("GRANT SELECT ON public.processed_events TO assetflow_api")
    op.execute("GRANT SELECT, INSERT, DELETE ON public.processed_events TO assetflow_worker")
    op.execute("GRANT SELECT ON public.processed_events TO assetflow_readonly")
    op.execute("GRANT ALL ON public.processed_events TO assetflow_migrator")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.processed_events CASCADE")
    op.execute("DROP TABLE IF EXISTS public.outbox CASCADE")
    op.execute("DROP TABLE IF EXISTS public.audit_events CASCADE")
