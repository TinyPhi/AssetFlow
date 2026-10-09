<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# Testing Guide

This guide covers the testing strategy, standards, and verification suites used across AssetFlow.

## Authorization Matrix

AssetFlow enforces compile-time and test-time authorization guarantees for every HTTP API endpoint per master plan §B11.6, §C8.4, and Gate G1.

The authorization matrix tests are located in `backend/tests/authz_matrix/` and run automatically under `make test-backend` and `make verify`.

### Route Authorization Declarations

Every route exposed by FastAPI must explicitly declare either:
1. A required permission via `openapi_extra=permission_extra("<permission>")`:
   ```python
   from app.api.deps import permission_extra

   @router.get("/assets", openapi_extra=permission_extra("asset.read"))
   async def list_assets(...):
       ...
   ```
2. Or an explicit public route marker via `openapi_extra=public_extra()`:
   ```python
   from app.api.deps import public_extra

   @router.get("/healthz", openapi_extra=public_extra())
   async def healthz(...):
       ...
   ```

Any route lacking both declarations will fail `test_every_route_has_permission_or_public_declaration` with the route method and path.

### Authorization Matrix Test Generator

The matrix test (`tests/authz_matrix/test_matrix.py`):
1. Enumerates all API routes and their HTTP methods from the OpenAPI specification.
2. Evaluates each role defined in `ROLE_PERMISSIONS` (`admin`, `asset_manager`, `planner`, `team_lead`, `technician`, `member`) plus unassigned `"none"`.
3. Verifies that callers holding permission receive 2xx (or domain validation errors), and callers without permission receive `403 Forbidden` or `404 Not Found` (never 2xx).
4. Asserts bidirectional separation between platform-level and tenant-level access.

### Adding an Exception

When a route legitimately diverges from standard RBAC permission checks (e.g. `GET /api/v1/me` which allows any authenticated tenant member to fetch their own profile regardless of specific `member.read` permission), document the exception in:
`backend/tests/authz_matrix/exceptions.yaml`

Each entry **must** contain:
- `route`: The API route pattern (e.g. `/api/v1/me`)
- `method`: HTTP method in uppercase (`GET`, `POST`, `PUT`, `PATCH`, `DELETE`)
- `role`: Role key being granted or denied
- `expected`: Either `allow` or `deny`
- `reason`: A clear explanation of why this exception is necessary and valid

Example:
```yaml
- route: /api/v1/me
  method: GET
  role: member
  expected: allow
  reason: "Every authenticated member can read their own identity and effective permissions without explicit member.read grant (§C4.9, M1.6-T1)"
```

The test runner validates that:
- Every exception has a non-empty reason.
- Every exception points to an existing API route. Stale exceptions for removed routes will fail the test.

### Running Matrix Tests

To run the authorization matrix suite directly:
```bash
cd backend
uv run pytest tests/authz_matrix -v
```
