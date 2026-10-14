# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""An anonymous request never gains identity from x-* headers (NEW-5, §C5.4)."""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from tests.authz_matrix.conftest import TEST_MEMBER_ID, TEST_ORG_ID
from tests.authz_matrix.factories_map import build_route_url, get_query_params, get_request_body
from tests.authz_matrix.test_matrix import _get_api_routes

# This module runs against the real AuthMiddleware, without the test-only header identity.
REAL_AUTH = True

FORGED = {
    "x-member-id": TEST_MEMBER_ID,
    "x-organization-id": TEST_ORG_ID,
    "x-role": "admin",
    "x-scope-type": "organization",
    "x-platform-admin": "true",
}


async def test_anonymous_request_with_identity_headers_is_401_on_every_protected_route(
    authz_app: FastAPI,
) -> None:
    transport = httpx.ASGITransport(app=authz_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for path, method, spec in _get_api_routes(authz_app):
            if spec.get("x-assetflow-public"):
                continue
            res = await client.request(
                method,
                build_route_url(path),
                params=get_query_params(path),
                json=get_request_body(method, path),
                headers=FORGED,
            )
            assert res.status_code == 401, f"{method} {path} answered {res.status_code} to forged headers"
