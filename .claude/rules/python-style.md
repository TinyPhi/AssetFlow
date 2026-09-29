---
paths:
  - "backend/**/*.py"
---

# Python style (backend)

Source: plan §B4.2, §B12.4, §C1.3, §C1.5, §C4.1–§C4.7, §C4.10, §C7.4, §C12.

## Toolchain

- Python 3.12 only, managed with `uv`. `ruff` (lint + format, line length 110). `mypy --strict` with the Pydantic plugin on `core`, `providers`, `channels`, `engines` (and growing on modules).
- Async all the way. Blocking work goes to the worker or a threadpool.
- Run `make fmt`, `make lint`, `make typecheck` before `af.py verify`.

## File header (every file)

```python
# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
```

Use the current year. Files that cannot carry a comment go in `REUSE.toml`.

## Layering: router -> service -> repository

Each module in `backend/app/modules/<module>/` has `router.py`, `service.py`, `repository.py`, `schemas.py`, `events.py`, `permissions.py`, `config.py`, `errors.py` (§C4.1).

- **Router** (§C4.2): receive validated input; get the request context; route-level `require("<entity>.<action>")` dependency (or `public_route(rate_limit=...)`); call **exactly one** service method; return the success envelope. No DB, no providers, no `if` business checks.
- **Service** (§C4.3): one transaction per write command, in this order:
  1. load the record `FOR UPDATE` (raise `<Entity>NotFound`);
  2. `ctx.scope.require(permission, record)` on the **loaded record**;
  3. check the workflow transition if state changes;
  4. write with the client's `version` (raise `<Entity>VersionConflict` on 0 rows);
  5. write the `audit_events` row (actor, action, before/after; no personal values);
  6. write the `outbox` row with the domain event;
  7. commit, return the updated record.
  Never call email, a channel or an external API inside a request: publish an event.
- **Repository** (§C4.4): SQL only (asyncpg), `$n` parameters only, never string-formatted user input. List methods take a `ScopeFilter` argument (a test fails otherwise), use `UNION ALL` of ids de-duplicated before ordering and cursor paging, fetch `limit + 1`. No `SELECT *` in lists. Every `UPDATE` of a versioned table has `AND version = $n` and `version = version + 1`.
- `asyncpg` is imported only in `core/db.py` and repositories (import-linter). Tenant connections come only from `ctx.db.transaction()` (worker: `worker_context(organization_id)`).
- Never rely on a manual `organization_id` filter as the only protection; RLS enforces it.

## Module and layer boundaries (import-linter, §C12)

- Layers top to bottom: `api` -> `modules` -> `engines` -> `channels` -> `providers` -> `core`. Import only downward.
- A module never imports another module's repository; call its service or publish an event.
- Only providers and channels import vendor SDKs (PyJWT, OpenBao client, OTel exporters, SMTP). The PDF library only in `core/pdf`.
- Providers receive typed values plus `organization_id`, never request objects.

## Naming (§C1.2, §C1.3)

- Neutral vocabulary only: `organization`, `org_unit`, `team`, `member`, `location`, `asset`, `work_order`, `work_request`. Never `tenant`, `department`, `employee`, `user`, `ticket`, `job`.
- Classes: `WorkOrderService`, `WorkOrderRepository`, `WorkOrderCreate` / `WorkOrderUpdate` / `WorkOrderRead`, `WorkOrderNotFound`.
- Permissions `<entity>.<action>`; events `<entity>.<what_happened>`; error codes `<area>.<reason>`; spans `service.<entity>.<command>`, `worker.<job>.run`; metrics `assetflow_<area>_<measure>_<unit>`.
- Status and state values are text validated against domain config, never Python or PostgreSQL enums.

## Validation and errors

- Pydantic models at every boundary (request bodies, config, events, connector settings). Connector/provider settings are Pydantic models published as JSON Schema (D17); secret fields use `SecretStr` and are write-only.
- Raise module errors (subclasses of `NotFound`, `VersionConflict`, `InvalidTransition`, `PermissionDenied`, `ScopeDenied`, `ValidationFailed`, `RateLimited`), never `HTTPException`.
- The error middleware returns RFC 9457 `application/problem+json`: `type`, `title`, `status`, `detail`, `instance`, plus extensions `code`, `request_id`, `errors[]` (`field`, `message`). `detail` never contains SQL, stack traces, secrets or other members' personal data.
- Scope failures on reads return 404, not 403.
- No bare `except`; no blind `except Exception` without re-raise or a logged, typed reason.

## Logging, tracing, config, time

- Log only through the telemetry logger (OpenTelemetry). Message = stable event name (`work_order.dispatched`); details in structured fields: `request_id`, `trace_id`, `organization_id`, `member_id` (pseudonymous), `event_type`, `error_code`.
- **Never log** tokens, cookies, passwords, scan tokens, emails, phone numbers, names, request/response bodies or SQL parameters. The scrubber is the second line of defence.
- No `print`. No `os.environ` outside `core/config.py`; read `assetflow.core.config.settings` and `ctx.domain`. New config keys: Pydantic field with description, a default or a clear validation error.
- Read time only through `core.clock`. Timestamps are UTC `timestamptz`; IDs are UUIDv7 from `uuid7()`.

## Size and comments

- Files under 400 lines, functions under 60 lines.
- Default: no comment. Comment only a non-obvious *why*. One-line docstrings on public functions in `core`, `providers`, `channels`, `engines`, and on route functions (becomes the OpenAPI summary).
- No commented-out code. `# TODO(#142): ...` only with an issue number.
