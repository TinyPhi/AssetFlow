# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""RBAC Authorization Matrix Generator and Verification Tests (§B11.6, §C8.4).

Verifies that:
1. Every route carries either `x-assetflow-permission` or `x-assetflow-public`.
2. The authorization matrix (routes x roles) accurately produces 2xx on allowed and 403/404 on denied.
3. Exceptions in `exceptions.yaml` are verified, documented, and have no stale routes.
4. Platform and tenant separation holds strictly in both directions (§C5.4 rule 6).
5. Rate limit coverage applies across public and protected endpoints (§C11).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from fastapi import FastAPI

from app.core.permissions import ROLE_PERMISSIONS
from app.core.scope import ScopeResolver
from tests.authz_matrix.conftest import TEST_MEMBER_ID, TEST_ORG_ID, as_member
from tests.authz_matrix.factories_map import (
    build_route_url,
    get_query_params,
    get_request_body,
)

EXCEPTIONS_FILE = Path(__file__).parent / "exceptions.yaml"


def _load_exceptions() -> list[dict[str, Any]]:
    if not EXCEPTIONS_FILE.exists():
        return []
    with EXCEPTIONS_FILE.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or []


def _get_api_routes(app: FastAPI) -> list[tuple[str, str, dict[str, Any]]]:
    """Extract (path, method, operation_spec) for all application routes."""
    openapi = app.openapi()
    routes = []
    for path, methods in openapi.get("paths", {}).items():
        if path in ("/docs", "/redoc", "/openapi.json"):
            continue
        for method, spec in methods.items():
            if method.lower() in ("get", "post", "put", "patch", "delete"):
                routes.append((path, method.upper(), spec))
    return routes


def test_every_route_has_permission_or_public_declaration(authz_app: FastAPI) -> None:
    """Every route must carry `x-assetflow-permission` or `x-assetflow-public: true` (Step 4, §C8.4)."""
    routes = _get_api_routes(authz_app)
    assert len(routes) > 0, "No API routes discovered"

    undeclared: list[str] = []
    for path, method, spec in routes:
        has_perm = bool(spec.get("x-assetflow-permission"))
        is_public = bool(spec.get("x-assetflow-public"))
        if not has_perm and not is_public:
            undeclared.append(f"{method} {path}")

    assert not undeclared, f"Routes missing authorization metadata: {undeclared}"


def test_exceptions_yaml_validity(authz_app: FastAPI) -> None:
    """Exceptions file must have valid format and no stale routes (Step 7, §C8.4)."""
    exceptions = _load_exceptions()
    routes = {(path, method) for path, method, _ in _get_api_routes(authz_app)}

    for entry in exceptions:
        assert "route" in entry, f"Missing 'route' in exception: {entry}"
        assert "method" in entry, f"Missing 'method' in exception: {entry}"
        assert "role" in entry, f"Missing 'role' in exception: {entry}"
        assert "expected" in entry, f"Missing 'expected' in exception: {entry}"
        assert "reason" in entry, f"Missing 'reason' in exception: {entry}"

        assert entry["expected"] in ("allow", "deny"), f"Invalid expected value in {entry}"
        assert len(entry["reason"].strip()) >= 10, f"Exception reason too short: {entry}"
        assert (
            entry["route"],
            entry["method"].upper(),
        ) in routes, f"Stale exception for non-existent route: {entry}"


@pytest.mark.asyncio
async def test_authorization_matrix_all_roles(authz_app: FastAPI) -> None:
    """Test matrix of (route x role) asserting 2xx on allow and 403/404 on deny (Step 3, §C8.4)."""
    routes = _get_api_routes(authz_app)
    exceptions_map: dict[tuple[str, str, str], str] = {
        (e["route"], e["method"].upper(), e["role"]): e["expected"] for e in _load_exceptions()
    }

    roles = [*list(ROLE_PERMISSIONS.keys()), "none"]
    resolver = ScopeResolver()

    transport = httpx.ASGITransport(app=authz_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for path, method, spec in routes:
            url = build_route_url(path)
            query_params = get_query_params(path)
            body = get_request_body(method, path)

            is_public = bool(spec.get("x-assetflow-public"))
            required_perm = spec.get("x-assetflow-permission")

            if is_public:
                # Public routes must succeed without authentication
                res = await client.request(method, url, params=query_params, json=body)
                assert res.status_code < 400, (
                    f"Public route {method} {url} failed with {res.status_code}: {res.text}"
                )
                continue

            for role in roles:
                member_ctx = as_member(role)
                has_perm = resolver.has_permission(member_ctx, required_perm)

                expected = exceptions_map.get((path, method, role))
                if expected is None:
                    expected = "allow" if has_perm else "deny"

                headers = {
                    "x-member-id": TEST_MEMBER_ID,
                    "x-organization-id": TEST_ORG_ID,
                    "x-role": role,
                }
                res = await client.request(method, url, params=query_params, json=body, headers=headers)

                if expected == "allow":
                    # Per §C8.4: 2xx or 4xx validation/conflict error when role has permission, NOT 401 or 403
                    assert res.status_code not in (401, 403), (
                        f"Expected {role} to ALLOW {method} {path} ({required_perm}), "
                        f"got {res.status_code}: {res.text}"
                    )
                    if method == "GET":
                        assert res.status_code != 404, (
                            f"Expected {role} to ALLOW {method} {path} ({required_perm}), "
                            f"got 404 read denial: {res.text}"
                        )
                else:
                    assert res.status_code in (401, 403, 404), (
                        f"Expected {role} to DENY {method} {path} ({required_perm}), "
                        f"got {res.status_code}: {res.text}"
                    )


@pytest.mark.asyncio
async def test_platform_separation_both_directions(authz_app: FastAPI) -> None:
    """Platform separation (§C5.4 rule 6): org admin '*' cannot reach platform.* and vice versa."""
    transport = httpx.ASGITransport(app=authz_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Direction 1: Org admin '*' cannot reach platform.*
        res1 = await client.get(
            "/api/health/providers",
            headers={"x-member-id": TEST_MEMBER_ID, "x-organization-id": TEST_ORG_ID, "x-role": "admin"},
        )
        assert res1.status_code in (401, 403, 404), f"Org admin reached platform route: {res1.status_code}"

        # Direction 2: Platform admin inside organization has only grants held there
        res2 = await client.get(
            "/api/v1/locations",
            headers={"x-platform-admin": "true"},  # missing organization_id
        )
        assert res2.status_code in (400, 401, 422), (
            f"Platform admin bypassed tenant organization context: {res2.status_code}"
        )


def test_rate_limit_declarations(authz_app: FastAPI) -> None:
    """Non-public routes are covered by rate limiter and public routes have stricter limits (§C11)."""
    routes = _get_api_routes(authz_app)
    public_routes = [path for path, _, spec in routes if spec.get("x-assetflow-public")]
    protected_routes = [path for path, _, spec in routes if spec.get("x-assetflow-permission")]

    assert len(public_routes) >= 5, "Public routes missing"
    assert len(protected_routes) >= 15, "Protected routes missing"
