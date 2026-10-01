---
name: new-module
description: Scaffold an AssetFlow backend module or module feature (router/service/repository/schemas/events/permissions/config/errors) plus its frontend feature folder, following §C4. Use for "new module", "add a feature to assets/maintenance/organization", "add entity", "new sub-folder like assets/custody".
---

# New module or module feature

Needs an approved plan whose `scope_paths` cover every path below. Work inside one transaction per command,
RLS for the organization boundary, the scope resolver for org unit/team/self.

## Backend files (`backend/app/modules/<module>/` or a sub-folder with the same shape)

| File | Holds | Rules |
| --- | --- | --- |
| `router.py` | HTTP only | receive params + body, `require("<entity>.<action>")` or `public_route(rate_limit=...)`, call exactly one service method, return the success envelope. No DB, no providers, no `if` logic. One-line docstring per route (OpenAPI summary). |
| `service.py` | business rules, permission and scope, transactions | write command in ONE `ctx.db.transaction()`: load + `FOR UPDATE` -> not found error -> `ctx.scope.require(permission, record)` -> workflow transition check -> write with expected `version` -> audit event -> outbox row -> commit. Span `service.<entity>.<command>`. Never call channels, email or external APIs; publish an event. |
| `repository.py` | SQL only (asyncpg) | `$n` parameters only; list methods take `scope: ScopeFilter` (UNION ALL of id branches, de-duplicated, then order + cursor page with limit+1); no `SELECT *` in lists; `UPDATE ... WHERE id = $1 AND version = $2` and raise version conflict on 0 rows. |
| `schemas.py` | Pydantic v2 | `<Entity>Create`, `<Entity>Update` (includes `version`), `<Entity>Read`; field descriptions; snake_case JSON. |
| `events.py` | event types | `<entity>.<what_happened>`, payload model with descriptions, `schema_version`. |
| `permissions.py` | declared permissions | `<entity>.<action>` with descriptions (generates `docs/reference/permissions.md`). |
| `config.py` | module section of the domain template | Pydantic fields with descriptions and defaults; statuses validated from config, not DB enums. |
| `errors.py` | module errors | `<Entity>NotFound` (404 `<entity>.not_found`), `<Entity>VersionConflict` (409), `InvalidTransition`; never `HTTPException`. |

Wire the router in `backend/app/api/v1/router.py`. Tables come from the `new-migration` skill; routes from `new-route`.

Reads failing scope raise not-found (404), not 403. Organization context is set only by `ctx.db.transaction()`
(`SELECT set_config('app.organization_id', $1, true)`); never import `asyncpg` outside `core/db.py` and repositories.
Settings via `assetflow.core.config.settings` and `ctx.domain`; no `os.environ`. Log stable event names with structured
fields; never tokens, emails, names, phone numbers, bodies or SQL parameters. Time via `core.clock`. Ids via `uuid7()`.

## Frontend (`frontend/src/features/<feature>/`)

`api/` (services over `lib/api` + query-key factory `[resource, scope, params]`), `hooks/` (`useWorkOrders`,
`useDispatchWorkOrder`), `components/`, `pages/`, `routes.tsx` (permission guards), `index.ts`.
Components never call `fetch`; UI text via `t("<feature>.<screen>.<element>")` with keys in `en.json`;
semantic Tailwind tokens only; list pages have loading/error/empty/data states; `usePermission(...)` hides actions
for convenience only. WCAG 2.2 AA, 320-2560 px layouts.

## Tests (name the test path after the module so the review gate matches it)

- `backend/tests/unit/<module>/test_<unit>.py` — pure rules, table-driven for config rules; hypothesis for invariants.
- `backend/tests/integration/<module>/test_<entity>_service.py` — per command: success, permission refusal,
  scope refusal, version conflict, invalid transition, audit row written, outbox row written. Real PostgreSQL 16.
- `backend/tests/isolation/test_<module>_<entity>.py` — org_a data invisible as org_b; unstamped connection sees 0 rows;
  cross-org insert refused; GET routes with org_a ids as org_b -> 404.
- `backend/tests/scope/test_<module>_<entity>.py` — sibling org unit 404 and absent from list; parent-unit manager allowed;
  record matching two scope branches appears once; revoked grant refused on next request.
- `backend/tests/e2e_api/` for new user-facing flows; `frontend/src/features/<feature>/**/*.test.tsx` for hooks/components.
- Factories in `backend/tests/factories.py` create rows through services. Faker with fixed seed, `example.org` emails.

## Security-path notes

`backend/app/modules/organization/` is a security path: grants (a member cannot grant what they lack), provisioning,
platform actions (`platform.*` never inside an organization). Any change there needs the `security-reviewer` agent.

## Docs

`docs/reference/*` regenerated (`make docs-check`), guide page for new screens, `CHANGELOG.md` under Unreleased.
Verify locally: `make lint`, `make typecheck`, `make test`, `make test-isolation` (then the loop's `af.py verify`).
