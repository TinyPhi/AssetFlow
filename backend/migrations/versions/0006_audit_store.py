# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Audit store: personal values table and partition maintenance (§B10, §1590, §2138).

Revision ID: 0006_audit_store
Revises: 0005_audit_and_outbox
Create Date: 2026-10-01 00:00:06.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006_audit_store"
down_revision: str | None = "0005_audit_and_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. audit_personal_values table
    op.execute("""
CREATE TABLE public.audit_personal_values (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    audit_event_id uuid NOT NULL,
    field_name text NOT NULL,
    field_value text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT audit_personal_values_pkey PRIMARY KEY (id),
    CONSTRAINT uq_audit_personal_values__org_id UNIQUE (organization_id, id),
    CONSTRAINT fk_audit_personal_values__organization_id__organizations
        FOREIGN KEY (organization_id) REFERENCES public.organizations (id) ON DELETE RESTRICT
)
""")
    op.execute("ALTER TABLE public.audit_personal_values OWNER TO assetflow_migrator")
    op.execute("ALTER TABLE public.audit_personal_values ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.audit_personal_values FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE INDEX ix_audit_personal_values__organization_id "
        "ON public.audit_personal_values (organization_id)"
    )
    op.execute(
        "CREATE INDEX ix_audit_personal_values__org_event "
        "ON public.audit_personal_values (organization_id, audit_event_id)"
    )

    op.execute(
        "CREATE POLICY audit_personal_values_select ON public.audit_personal_values "
        "FOR SELECT USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)"
    )
    op.execute(
        "CREATE POLICY audit_personal_values_insert ON public.audit_personal_values "
        "FOR INSERT WITH CHECK ("
        "organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)"
    )
    op.execute(
        "CREATE POLICY audit_personal_values_update ON public.audit_personal_values "
        "FOR UPDATE USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid) "
        "WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)"
    )
    op.execute(
        "CREATE POLICY audit_personal_values_delete ON public.audit_personal_values "
        "FOR DELETE USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)"
    )

    op.execute("GRANT SELECT, INSERT, DELETE ON public.audit_personal_values TO assetflow_api")
    op.execute("GRANT SELECT, DELETE ON public.audit_personal_values TO assetflow_worker")
    op.execute("GRANT SELECT ON public.audit_personal_values TO assetflow_readonly")
    op.execute("GRANT ALL ON public.audit_personal_values TO assetflow_migrator")

    # 2. Partition housekeeping function (§2138)
    op.execute("""
CREATE OR REPLACE FUNCTION platform.maintain_audit_partitions(
    base_date timestamptz DEFAULT clock_timestamp(),
    months_ahead integer DEFAULT 3
) RETURNS text[]
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    created text[] := '{}';
    m_start timestamptz;
    m_end timestamptz;
    m_name text;
    i integer;
    org record;
BEGIN
    FOR i IN 0 .. (months_ahead - 1) LOOP
        m_start := date_trunc('month', base_date) + (i || ' month')::interval;
        m_end := m_start + '1 month'::interval;
        m_name := 'audit_events_' || to_char(m_start, 'YYYY_MM');

        IF NOT EXISTS (
            SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relname = m_name
        ) THEN
            EXECUTE 'ALTER TABLE public.audit_events_default NO FORCE ROW LEVEL SECURITY';
            EXECUTE format(
                'CREATE TEMP TABLE _moved_audit ON COMMIT DROP AS '
                'WITH moved AS ('
                'DELETE FROM public.audit_events_default '
                'WHERE created_at >= %L AND created_at < %L RETURNING *'
                ') SELECT * FROM moved',
                m_start, m_end
            );
            EXECUTE 'ALTER TABLE public.audit_events_default FORCE ROW LEVEL SECURITY';

            EXECUTE format(
                'CREATE TABLE public.%I PARTITION OF public.audit_events FOR VALUES FROM (%L) TO (%L)',
                m_name, m_start, m_end
            );
            EXECUTE format('ALTER TABLE public.%I OWNER TO assetflow_migrator', m_name);

            FOR org IN EXECUTE 'SELECT DISTINCT organization_id FROM _moved_audit' LOOP
                PERFORM set_config('app.organization_id', org.organization_id::text, true);
                EXECUTE format(
                    'INSERT INTO public.%I SELECT * FROM _moved_audit WHERE organization_id = %L',
                    m_name, org.organization_id
                );
            END LOOP;
            PERFORM set_config('app.organization_id', '', true);
            EXECUTE 'DROP TABLE IF EXISTS _moved_audit';

            EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', m_name);
            EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', m_name);

            created := array_append(created, m_name);
        END IF;
    END LOOP;
    RETURN created;
END;
$$;
""")
    op.execute(
        "ALTER FUNCTION platform.maintain_audit_partitions(timestamptz, integer) OWNER TO assetflow_migrator"
    )
    op.execute("REVOKE ALL ON FUNCTION platform.maintain_audit_partitions(timestamptz, integer) FROM PUBLIC")
    op.execute(
        "GRANT EXECUTE ON FUNCTION platform.maintain_audit_partitions(timestamptz, integer) "
        "TO assetflow_worker, assetflow_api"
    )
    op.execute("GRANT USAGE ON SCHEMA platform TO assetflow_worker")

    # 3. Partition health check function (§2138)
    op.execute("""
CREATE OR REPLACE FUNCTION platform.audit_partition_health(
    base_date timestamptz DEFAULT clock_timestamp()
) RETURNS TABLE(
    healthy boolean, default_rows bigint, next_partition_exists boolean,
    next_partition_name text, alert boolean
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_next_month timestamptz;
    v_next_name text;
    v_def_rows bigint;
    v_exists boolean;
    v_healthy boolean;
BEGIN
    v_next_month := date_trunc('month', base_date) + '1 month'::interval;
    v_next_name := 'audit_events_' || to_char(v_next_month, 'YYYY_MM');

    EXECUTE 'ALTER TABLE public.audit_events_default NO FORCE ROW LEVEL SECURITY';
    SELECT count(*) INTO v_def_rows FROM public.audit_events_default;
    EXECUTE 'ALTER TABLE public.audit_events_default FORCE ROW LEVEL SECURITY';

    SELECT EXISTS (
        SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relname = v_next_name
    ) INTO v_exists;

    v_healthy := (v_def_rows = 0) AND v_exists;
    RETURN QUERY SELECT v_healthy, v_def_rows, v_exists, v_next_name, NOT v_healthy;
END;
$$;
""")
    op.execute("ALTER FUNCTION platform.audit_partition_health(timestamptz) OWNER TO assetflow_migrator")
    op.execute("REVOKE ALL ON FUNCTION platform.audit_partition_health(timestamptz) FROM PUBLIC")
    op.execute(
        "GRANT EXECUTE ON FUNCTION platform.audit_partition_health(timestamptz) "
        "TO assetflow_worker, assetflow_api"
    )


def downgrade() -> None:
    op.execute("REVOKE USAGE ON SCHEMA platform FROM assetflow_worker")
    op.execute("DROP FUNCTION IF EXISTS platform.audit_partition_health(timestamptz)")
    op.execute("DROP FUNCTION IF EXISTS platform.maintain_audit_partitions(timestamptz, integer)")
    op.execute("DROP TABLE IF EXISTS public.audit_personal_values CASCADE")
