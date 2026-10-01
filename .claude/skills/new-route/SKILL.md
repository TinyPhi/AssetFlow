---
name: new-route
description: Add an AssetFlow API endpoint (router -> one service method -> repository) with permission, scope, rate limit, RFC 9457 errors and authz-matrix coverage, following §C1.5 and §C4.2-C4.5. Use for "new endpoint", "add route", "add API", "expose X over HTTP", "public route".
---

# New route

## Path and shape (§C1.5)

- `/api/v1/<plural-kebab>/{<entity>_id}`; non-CRUD actions `POST /api/v1/<plural>/{id}/<verb>`.
  Public scan/report under `/api/public`; session under `/api/auth`.
- Query params snake_case; lists cursor-paged (`data.items`, `data.next_cursor`, `limit` default 50, max 200).
- Success envelope `{status, status_code, message, timestamp, request_id, data}`.
- Writes that update a record take `version`; mismatch -> 409 `<entity>.version_conflict`.
- `POST` honors `Idempotency-Key` (stored 24 h per member in `idempotency_keys`).

## Router (`backend/app/modules/<module>/router.py`)

```python
@router.post("/work-orders/{work_order_id}/dispatch", response_model=Envelope[WorkOrderRead])
async def dispatch_work_order(
    work_order_id: UUID,
    body: WorkOrderDispatch,
    ctx: RequestContext = Depends(require("work_order.dispatch")),
) -> Envelope[WorkOrderRead]:
    """Dispatch a work order to a team."""
    return envelope(await ctx.services.work_orders.dispatch(ctx, work_order_id, body))
```

- Exactly: validated input -> `require(...)` (or `public_route(rate_limit=...)`) -> ONE service call -> envelope.
- No DB, no providers, no `if` logic, no `HTTPException`.
- Public routes always declare a rate limit; also add the nginx zone in `deploy/nginx/` if the plan says so (security path).

## Service

- Re-check on the loaded record: `ctx.scope.require("work_order.dispatch", record)`; reads failing scope raise NotFound (404).
- Write path: one `ctx.db.transaction()` with lock, version check, audit event, outbox row (§C4.3).
- Permission `<entity>.<action>` declared in `permissions.py` with a description; default roles in `config/assetflow.yaml` if needed.

## Errors (RFC 9457, `application/problem+json`)

Module errors map to `type, title, status, detail, instance, code, request_id, errors`. `detail` never contains SQL,
stack traces, secrets or another member's personal data. New codes `<area>.<reason>` appear in the generated
`docs/reference/error-codes.md`.

## Tests

- `backend/tests/authz_matrix/` — generated from OpenAPI; the route must declare a permission or be public.
  Add to `exceptions.yaml` only with a reason.
- `backend/tests/integration/<module>/` — success, permission refusal (403), scope refusal (404 for reads), version conflict,
  invalid transition, validation error (422 `validation.invalid_field`), audit + outbox rows.
- `backend/tests/isolation/` — as org_b with an org_a id -> 404.
- `backend/tests/scope/` — sibling org unit -> 404 and absent from list; parent-unit manager allowed.
- `backend/tests/e2e_api/` — when the route is part of a user-facing flow.
- Public route: rate-limit test (429 `rate_limit.exceeded` with `Retry-After`), no data beyond `public_scan_fields`.

## Docs

OpenAPI from the docstring and field descriptions; `make docs-check` (regenerate reference with `make docs-generate`);
`CHANGELOG.md` for user-visible changes.

## Security-path notes

Routes in `modules/organization/`, `assets/qr/public*`, or anything in `core/permissions*` / `core/auth_middleware.py`
need the `security-reviewer` agent. Every new route is a STRIDE item for that review.
