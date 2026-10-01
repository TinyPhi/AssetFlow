---
paths:
  - "backend/migrations/**"
  - "backend/app/**/repositories*"
  - "backend/app/**/repository*"
  - "backend/tests/isolation/**"
  - "backend/tests/scope/**"
  - "**/*.sql"
---

# Database conventions

Source: plan D4, D5, D6, §B4.2 rule 6, §B5.2, §B5.3, §B9.3, §B10, §C1.4, §C4.4, §C4.8, §C5.4, §C8.5. Context: `.claude/context/rls-and-scopes.md`.

Every file in `backend/migrations/` is a **security path**: the security reviewer runs and the commit gate requires an isolation or scope test change in the same diff.

## Migrations

- Alembic, **raw SQL** (`op.execute(...)`). No autogenerate, no schema dumps, no ORM models.
- Create with `make migration name=<snake_description>`; file name `<YYYYMMDDHHMM>_<short_snake_description>.py`. The template adds the SPDX header and the tenant-table skeleton.
- Every migration has a working `downgrade()`. CI runs `upgrade head -> downgrade -1 -> upgrade head` and a schema drift check against `backend/migrations/schema.snapshot.sql`.
- Migrations run as `assetflow_migrator`. `assetflow_api` and `assetflow_worker` own nothing, cannot create objects, and have no `BYPASSRLS`.

## Every tenant table (the migration lint enforces this)

```sql
CREATE TABLE work_orders (
  id uuid PRIMARY KEY,                       -- UUIDv7 generated in the application
  organization_id uuid NOT NULL REFERENCES organizations(id),
  ...,
  version integer NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_work_orders__organization_id_state ON work_orders (organization_id, state);
ALTER TABLE work_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE work_orders FORCE ROW LEVEL SECURITY;
CREATE POLICY rls_work_orders_select ON work_orders FOR SELECT
  USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid);
-- rls_work_orders_insert (WITH CHECK), _update (USING + WITH CHECK), _delete: same predicate
```

- `organization_id NOT NULL`, **ENABLE and FORCE** RLS, **all four** policies, an index whose **first column is `organization_id`**.
- Policy predicate is exactly `organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid`, so an unset context matches no rows (fail-closed).
- Unique constraints include `organization_id` (`uq_members__organization_id_idp_subject`).
- Grants for `assetflow_api` / `assetflow_worker`: no `DELETE` unless the feature needs it. `audit_events` is insert-only for application roles.
- `updated_at` trigger (`fn_set_updated_at`). `organizations` is the one table scoped on `id`.
- Status/state columns are `text` validated from config, never PostgreSQL enums.

## Views and functions

- Every view: `CREATE VIEW v_<name> WITH (security_invoker = true) AS ...`. No materialized views on tenant data.
- `SECURITY DEFINER` functions (only `platform.resolve_organization`, `platform.list_active_organizations` and similar) set `search_path = pg_catalog, pg_temp`, use schema-qualified names, `REVOKE EXECUTE ... FROM PUBLIC`, and grant only to the one role that needs it.

## Naming (§C1.4)

Tables snake_case plural; PK `id`; FK `<singular>_id`; timestamps `<verb>_at timestamptz`; booleans `is_`/`has_`/`requires_`; `ix_<table>__<cols>`, `uq_<table>__<cols>`, `fk_<table>__<col>__<ref>`, `ck_<table>__<rule>`, `rls_<table>_<select|insert|update|delete>`, `v_<name>`, `trg_<table>__<purpose>`, `fn_<purpose>`. Roles: `assetflow_api`, `assetflow_worker`, `assetflow_migrator`, `assetflow_readonly`.

## Online changes (expand -> migrate -> contract)

- Never rename or drop a column in the same release that stops using it. Migrations stay forward-compatible for one minor release.
- Large tables (assets, work orders, audit and scan events): `CREATE INDEX CONCURRENTLY` inside an Alembic autocommit block.
- Partitioned tables (audit and scan events): `CREATE INDEX ... ON ONLY <parent>`, then `CREATE INDEX CONCURRENTLY` **per partition**, then `ALTER INDEX ... ATTACH PARTITION`.
- New required column: add nullable -> backfill in batches -> `ADD CONSTRAINT ck_<table>__<col>_not_null CHECK (<col> IS NOT NULL) NOT VALID` -> `VALIDATE CONSTRAINT` (then `SET NOT NULL` is cheap).
- A migration that still needs a long lock states it, with an estimated duration, in the release notes.

## Repositories

- asyncpg only here and in `core/db.py`. `$n` parameters only; the only formatted SQL parts are placeholder numbers produced by code.
- Connections come from `ctx.db.transaction()`, which runs `SELECT set_config('app.organization_id', $1, true)`. Worker: `worker_context(organization_id)`. Never take a raw pool connection in module code.
- List methods require a `ScopeFilter`: up to three indexed branches (org unit `path <@` via GiST on `ltree`, team ids, own member id) joined with `UNION ALL` of ids, de-duplicated before `ORDER BY`, count and cursor paging. Organization scope skips the filter.
- Versioned updates: `UPDATE ... SET ..., version = version + 1 WHERE id = $1 AND version = $2`; zero rows -> version conflict.
- No `SELECT *` in list queries. Check new list queries with `EXPLAIN` on realistic data.
- `organization_id` in `WHERE` is a hint only; RLS is the protection.

## Worker access (§B9.3)

- `assetflow_worker` may read claiming columns of `outbox` and `maintenance_schedules` across organizations through narrow policies only.
- Other sweeps call `platform.list_active_organizations()` then run each organization in its own short transaction under its context.

## Isolation and scope tests (required with every migration)

- `backend/tests/isolation/`: read isolation per repository method (auto-discovered), unstamped connection sees zero rows per table and view, cross-organization insert refused, `GET` routes with another organization's ids return 404, worker jobs for `org_a` never touch `org_b`.
- `backend/tests/scope/`: sibling org unit gets 404 and is absent from lists; parent-unit manager sees the child's record; revoked grant refused on the next request; a record matching two scope branches appears once.
- Discovery helpers `all_repository_read_methods()`, `tenant_tables()`, `tenant_tables_and_views()` cover new objects automatically; still add targeted cases for new behaviour.
