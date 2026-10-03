<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# Tenancy and scopes

How AssetFlow isolates organizations from each other, and how it limits what a member can see
and do inside their own organization. Two independent layers, enforced by different mechanisms
and tested by different suites.

| Boundary | Enforced by | Tested by |
| --- | --- | --- |
| Organization (tenant) | PostgreSQL row-level security, `FORCE`d, fail-closed | `backend/tests/isolation/` |
| Org unit / team / self | `ScopeResolver` + mandatory `ScopeFilter` on list queries | `backend/tests/scope/` |

Both run together: `cd backend && uv run pytest tests/isolation tests/scope -q`.

## Organization boundary

Every tenant table (`organizations` itself excepted — it has no parent tenant) has:

1. An `organization_id NOT NULL` column, first in its index.
2. Row-level security enabled **and forced** (`ALTER TABLE ... FORCE ROW LEVEL SECURITY`), so even
   the table owner is subject to policy.
3. Four policies — one each for `SELECT`, `INSERT`, `UPDATE`, `DELETE` — all using the same
   predicate: `organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid`.
   With no session context set, the setting is empty, `NULLIF` makes it `NULL`, and `NULL`
   compares false to everything: no rows readable, no write possible. The failure mode is "see
   nothing", never "see everything" or "error".

`app.core.db.tenant_transaction(pool, organization_id)` opens a connection, runs
`SELECT set_config('app.organization_id', $1, true)` as a parameterized `SET LOCAL` (never
string-interpolated), and yields the connection for the lifetime of that transaction only — the
setting does not leak to the next transaction on a pooled connection.

The API's database role (`assetflow_api`) is not the table owner and has no `BYPASSRLS`
attribute, so this is a real boundary, not a convention the application could accidentally step
around. Migrations run as a separate owner role (`assetflow_migrator`). Any view over a tenant
table is `security_invoker = true`, so it is checked under the querying role's own RLS, not the
view creator's.

### Resolving a tenant before you have one

Authentication happens before any `organization_id` is known, so it cannot run inside a tenant
transaction. Two narrow `SECURITY DEFINER` functions, owned by a dedicated `assetflow_resolver`
role with only the column grants they need, bridge this gap:

- `platform.resolve_organization(idp_organization_id)` — sign-in path; returns `(id, status)` or
  nothing, keyed only by the identity provider's own organization claim, never a client-supplied
  `org:id` scope. An unknown or archived organization answers exactly like a bad token: no
  enumeration of which organizations exist.
- `platform.find_organization_id(slug)` — used by `assetflow org create` to make slug collisions
  idempotent without granting the CLI's actor broad `SELECT` on `organizations`.

Both run under `platform_transaction(pool)`, which sets no tenant context at all — it is for
exactly this kind of cross-tenant platform lookup, never for regular request handling.

## Organization structure

- **Organization** — the tenant. Maps one-to-one to an identity-provider organization. Never
  created from a token; only `assetflow org create` (or the equivalent service call) creates one.
- **Org unit** — a tree per organization, materialized path (`path ltree`), recomputed atomically
  on every move with cycle prevention. Owns assets; the unit a resource belongs to (and its
  sub-units, via ltree subpath match) is what an `org_unit`-scoped grant covers.
- **Team** — flat, can span org units; a dispatch target. Membership (`team_members`) is
  time-bounded, not just present/absent.
- **Member** — one primary org unit, zero or more secondary ones, zero or more teams.
- **Location** — its own independent tree, unrelated to the org unit tree.

Archiving an org unit, team or location is blocked while it still has active children, members or
teams; the blocker returned names exactly which condition is in the way
(`active_children` / `active_members` / `active_teams`), not a generic refusal.

## Scopes

| Scope | A resource falls inside it when |
| --- | --- |
| `self` | the member is the resource's holder or assignee |
| `team` | the resource's `team_id` is the grant's team, or is one of the member's own team memberships |
| `org_unit` | the resource's owning org unit path equals the grant's unit path, or is a sub-unit of it |
| `organization` | always |

Grants live in `role_grants` (`role_key`, `scope_type`, `scope_id`, `source` = `idp` \| `manual`,
optional `expires_at`). Role keys and their permission sets are the fixed defaults in
`app.core.permissions.ROLE_PERMISSIONS` (`admin`, `asset_manager`, `planner`, `team_lead`,
`technician`, `member`); permissions use an `<entity>.<action>` naming pattern, with a `*`
wildcard only at the end of a segment (`asset.*` satisfies `asset.read`; `admin`'s bare `*`
satisfies every organization permission but never a `platform.*` one).

A member may only grant a role if they themselves hold every one of that role's permissions at a
scope covering the grant's target (`app.modules.organization.grants.can_grant`); revoking a grant
requires the same standing as granting it.

### How a check runs

- **A single loaded record**: `ScopeResolver.require(member, permission, resource)` (or
  `.check_access` for a boolean). A denied **read** answers `404 Not Found` — nothing is revealed
  about the resource's existence outside the caller's scope. A denied **write or other action**
  (create, update, grant, import, archive, ...) answers `403 Forbidden`. This split comes from the
  master plan's error-class table and tenancy rules, not from this feature's own plan file where
  the two can disagree — see `grants.py`, `bulk_import.py`, `org_settings.py` for the write side
  and `org_units.py` / `locations.py` / `teams.py` for the read side.
- **A list**: `ScopeResolver.resolve_scope_filter(member, permission)` builds a `ScopeFilter` once
  per request; repository list methods take it as a required argument, never an optional one, so a
  handler cannot forget to constrain a list query. Organization-scope grants short-circuit to
  `ScopeFilter.all_organization()` and skip the narrower checks entirely.

### No grant cache

Unlike the aspirational design in the project's internal engineering notes (a 60-second
in-process cache invalidated by `LISTEN/NOTIFY`), the implementation shipped for M1.4 does not
cache `MemberContext` or its grants at all: `AuthMiddleware` rebuilds the member's context from
the database on **every** request (see `app/core/auth_middleware.py`). A grant, revoke or
suspension takes effect on the very next request, by construction, with no invalidation path to
get wrong. If a cache is added later for latency reasons, it must preserve this property:
revocation must be visible to the next request, not the next cache expiry.

Suspension (of the organization or the member) is checked the same way, every request, never
cached. A suspended member is still recognized — the request is told its target is out of scope
(`404`), never that it is unauthenticated — so suspension cannot be distinguished from "this
resource doesn't exist" by an outside observer.

## Provisioning at sign-in

See [member provisioning policies](../guides/admin/member-provisioning.md) for the three
policies (`invite_only`, `require_role`, `open`) and their exact linking/creation rules. The one
tenancy-relevant invariant: while an organization is suspended, no new member is ever provisioned
or linked, even for a principal who would otherwise qualify — suspension must not be resumable
into unreviewed new access just by waiting for the organization to be reactivated.

## Typical mistakes this design rules out

- Filtering by `organization_id` in application SQL instead of relying on RLS: still safe (RLS
  still applies), but redundant and a sign the author doesn't trust the boundary — remove it.
- Checking a permission at the route level only, against no loaded record: misses `self`/`team`/
  `org_unit` scoping entirely; always check against the record that was actually loaded.
- A list method that accepts an optional `ScopeFilter`: makes "forgot to scope this list" a type
  error waiting to happen instead of a type error today.
- A view without `security_invoker = true`, or a `SECURITY DEFINER` function without a fixed,
  narrow `search_path` and column-level grants.
- Treating a denied read and a denied write the same way: a read denial that leaked as 403 would
  confirm the resource exists; a write denial that leaked as 404 would be confusing but not
  dangerous — the project still treats it as a defect (see the P5-05/P5-07/P5-09 fixes in
  `TRACKER.md`).
