# Context: tenancy (RLS) and scopes

Orientation for anyone touching `core/db*`, `core/permissions*`, repositories, `modules/organization/`, migrations or the isolation/scope suites. Plan sections: D4, D7, D13, §B5.1–§B5.7, §B9.3, §B10, §B11.1, §C4.4, §C4.8, §C5.4, §C8.5.

## Two layers, two suites

| Boundary | Enforced by | Tested by |
| --- | --- | --- |
| Organization (tenant) | PostgreSQL RLS, `FORCE`, fail-closed policies (D4, §B10) | `backend/tests/isolation/` |
| Org unit / team / self | Scope resolver + mandatory `ScopeFilter` (§B5.3) | `backend/tests/scope/` |

Both run in `make test-isolation` and in CI `tenant-isolation` (always on `main`).

## Organization boundary (§C5.4)

1. Every tenant table has `organization_id NOT NULL`, RLS enabled **and forced**, four policies, an `organization_id`-first index (§C4.8).
2. `ctx.db.transaction()` runs `SELECT set_config('app.organization_id', $1, true)` (parameterized `SET LOCAL`).
3. Policies: `organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid`. No context -> no rows, writes fail.
4. API role is not the owner and has no `BYPASSRLS`. Migrations use `assetflow_migrator`. Views are `security_invoker`.
5. Sign-in lookup before any context: only `platform.resolve_organization(idp_organization_id)` (`SECURITY DEFINER`, returns `(id, status)`) (§B5.2).
6. Worker: `worker_context(organization_id)`; cross-organization discovery only via `platform.list_active_organizations()` and narrow claiming policies on `outbox` and `maintenance_schedules` (§B9.3).

## Organization structure (§B5.1, §B5.2, D13)

- **Organization**: the tenant; maps 1:1 to an IdP organization. Never created from a token.
- **Org unit**: tree (`path ltree`, maintained by trigger); owns assets; defines access scope.
- **Team**: flat, can span org units; dispatch target. Time-bounded `team_members`.
- **Member**: one primary org unit, optional secondary ones, 0..n teams.
- **Location**: its own tree, independent of org units.
- An asset is owned by an org unit, located at a location, held by a member, maintained by a team.

## Scopes (§B5.3, D7)

| Scope | Covers a resource when |
| --- | --- |
| `self` | member is holder or assignee (automatic, baseline permissions) |
| `team` | resource `team_id` equals the grant's team |
| `org_unit` | resource `owner_org_unit_path <@` grant's unit path (unit and all sub-units) |
| `organization` | always |

- Grants live in `role_grants` (`scope_type`, `scope_id`, `source` = `idp` | `manual`, `expires_at`). Role keys must exist in config.
- IdP project roles -> organization-scope grants, re-synced at login **and every token refresh**; `manual` grants are never touched by sync.
- A member can only grant a role whose every permission they hold at a covering scope (`role_grant.manage`).
- `admin`'s `*` = all organization permissions, never `platform.*`.

## How a check runs

- Record: `require("asset.assign", resource)` / `ctx.scope.require(permission, record)` on the **loaded** record. Denied reads -> 404; denied writes -> 403 `scope.denied`.
- List: a `ScopeFilter` built once per request; repository list methods cannot be called without it. It becomes up to three indexed branches (org unit paths via GiST, team ids, own member id) joined by `UNION ALL` of ids, de-duplicated before ordering/count/cursor. Organization scope skips it.

## Caching and invalidation

- Effective grants cached per member for at most 60 s.
- Any grant, membership or member-status change publishes `grants_changed` via `LISTEN/NOTIFY`; every API and worker process drops that member's cache immediately.
- `LISTEN` uses one dedicated direct connection per process (PgBouncer transaction mode cannot carry it). Losing it clears the whole cache.
- Suspension is checked on every request, uncached.

## Provisioning (§B5.6)

`require_role` (default), `invite_only` (link only with `email_verified=true`, exact normalized email, matching IdP organization; never re-link), `open` (production needs `platform.allow_open_provisioning: true`). Failure -> `403 auth.not_provisioned` revealing nothing.

## Typical mistakes to avoid

- Filtering by `organization_id` in SQL and skipping RLS.
- Checking permission at the route but not on the loaded record.
- A list method with an `OR` across scope branches (loses index use) or without de-duplication.
- A view without `security_invoker`; a `SECURITY DEFINER` function without a fixed `search_path`.
- Caching suspension, or waiting for cache expiry after a revoke.
