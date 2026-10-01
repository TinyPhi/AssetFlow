---
name: new-migration
description: Create an AssetFlow Alembic raw-SQL migration (tenant table, column change, index, view, SECURITY DEFINER function) that passes check-migrations.py and §C4.8. Use for "new migration", "add table", "add column", "add index", "make migration", "alter schema".
---

# New migration

`backend/migrations/` is a security path: SECURITY step needs `security-reviewer` and `migration-reviewer`.
The commit gate refuses a migration without a changed test under `backend/tests/isolation/` or `backend/tests/scope/`.
A schema change not in the approved plan is a BLOCKER, not an improvisation.

## Create

`make migration name=<short_snake_description>` -> `backend/migrations/versions/<YYYYMMDDHHMM>_<name>.py`
(template includes SPDX header and the tenant-table skeleton). Raw SQL via `op.execute(...)`; no ORM, no autogenerate.

## Tenant table template

```sql
CREATE TABLE work_orders (
  id uuid PRIMARY KEY,                                   -- uuid7() from the application
  organization_id uuid NOT NULL
    CONSTRAINT fk_work_orders__organization_id__organizations REFERENCES organizations (id),
  number text NOT NULL,
  state text NOT NULL CONSTRAINT ck_work_orders__state_format CHECK (state ~ '^[a-z_]+$'),
  owner_org_unit_path ltree NOT NULL,
  team_id uuid,
  version integer NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_work_orders__organization_id_number UNIQUE (organization_id, number)
);
CREATE INDEX ix_work_orders__organization_id_state ON work_orders (organization_id, state);
CREATE INDEX ix_work_orders__owner_org_unit_path ON work_orders USING gist (owner_org_unit_path);
ALTER TABLE work_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE work_orders FORCE ROW LEVEL SECURITY;
CREATE POLICY rls_work_orders_select ON work_orders FOR SELECT
  USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid);
CREATE POLICY rls_work_orders_insert ON work_orders FOR INSERT
  WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid);
CREATE POLICY rls_work_orders_update ON work_orders FOR UPDATE
  USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
  WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid);
CREATE POLICY rls_work_orders_delete ON work_orders FOR DELETE
  USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid);
GRANT SELECT, INSERT, UPDATE ON work_orders TO assetflow_api, assetflow_worker;   -- DELETE only if the feature needs it
CREATE TRIGGER trg_work_orders__updated_at BEFORE UPDATE ON work_orders
  FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();
```

`downgrade()`: `DROP TABLE work_orders;` (policies, indexes and trigger go with it).
Unset context -> `NULLIF` yields NULL -> no rows match (fail-closed). No PostgreSQL enums for states.

## Views and functions

- `CREATE VIEW v_<name> WITH (security_invoker = true) AS ...`; no materialized views on tenant data.
- `SECURITY DEFINER` only when the plan says so:
  ```sql
  CREATE FUNCTION platform.resolve_organization(p text) RETURNS TABLE (id uuid, status text)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp
    AS $$ SELECT o.id, o.status FROM public.organizations o WHERE o.idp_organization_id = p $$;
  REVOKE EXECUTE ON FUNCTION platform.resolve_organization(text) FROM PUBLIC;
  GRANT EXECUTE ON FUNCTION platform.resolve_organization(text) TO assetflow_api;
  ```

## Changing existing tables (expand -> migrate -> contract)

- Never rename or drop in the release that stops using the column; contract is a later migration.
- Required column: add nullable -> batched idempotent backfill -> `ADD CONSTRAINT ck_<t>__<col>_not_null CHECK (<col> IS NOT NULL) NOT VALID`
  -> `VALIDATE CONSTRAINT` -> `ALTER COLUMN <col> SET NOT NULL` -> drop the check.
- Large tables (assets, work orders, audit and scan events): `CREATE INDEX CONCURRENTLY` inside
  `with op.get_context().autocommit_block():`.
- Partitioned tables (audit and scan events): `CREATE INDEX ix_p ON ONLY parent (...)`; for each partition
  `CREATE INDEX CONCURRENTLY ix_p_<part> ON <part> (...)` then `ALTER INDEX ix_p ATTACH PARTITION ix_p_<part>`.
- Any remaining long lock: state it, with estimated duration, for the release notes' upgrade notes.
- `downgrade()` reverses every step; CI runs upgrade -> downgrade -> upgrade.

## Tests

- `backend/tests/isolation/test_<table>.py` (discovery via `tenant_tables()` / `tenant_tables_and_views()` must include it):
  org_a rows invisible as org_b; unstamped connection sees 0 rows; insert claiming org_a while running as org_b refused.
- `backend/tests/scope/` when the table carries org unit/team/self scope.
- For SECURITY DEFINER: an unstamped API connection gets only the minimal result; other roles cannot execute.

## Check

`uv run python scripts/check-migrations.py`, `make migrate`, `make lint`, `make test-isolation`.
Then invoke `migration-reviewer`, then `security-reviewer` (SECURITY step). Docs: `docs/operations/upgrade.md`
if an operator step is needed.
