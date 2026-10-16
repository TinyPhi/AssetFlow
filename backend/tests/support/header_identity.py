# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Test-only identity: build the request member from x-* headers instead of a real sign-in.

The application never trusts these headers (NEW-5). This pytest plugin swaps `AuthMiddleware`
for a subclass that, when a request carries no bearer token, turns the headers below into
`request.state.member`, so route tests can act as a member of any organization without an
identity provider. A test module that must see the real middleware sets ``REAL_AUTH = True``.

Headers: x-member-id, x-organization-id (both required), x-role (default admin), x-scope-type,
x-scope-id, x-org-unit-path, x-team-ids (comma separated), x-platform-admin ("true").
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from starlette.types import Receive, Scope, Send

import app.main as app_main
from app.core.auth_middleware import AuthMiddleware
from app.core.permissions import ScopeType
from app.core.scope import MemberContext, RoleGrant


def member_from_headers(headers: dict[str, str]) -> MemberContext | None:
    """The member the headers describe, or None when member and organization ids are missing."""
    mid, oid = headers.get("x-member-id"), headers.get("x-organization-id")
    if not (mid and oid):
        return None
    st_raw = headers.get("x-scope-type", "organization")
    grant = RoleGrant(
        id="g",
        organization_id=oid,
        role_key=headers.get("x-role", "admin"),
        scope_type=ScopeType(st_raw) if st_raw in ScopeType else ScopeType.ORGANIZATION,
        scope_id=headers.get("x-scope-id"),
        org_unit_path=headers.get("x-org-unit-path"),
    )
    team_ids = tuple(headers["x-team-ids"].split(",")) if headers.get("x-team-ids") else ()
    return MemberContext(member_id=mid, organization_id=oid, grants=(grant,), team_ids=team_ids)


class HeaderIdentityAuthMiddleware(AuthMiddleware):
    """`AuthMiddleware` plus the test-only header identity for requests without a bearer token."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and not any(n.lower() == b"authorization" for n, _ in scope["headers"]):
            headers = {n.decode("latin-1").lower(): v.decode("latin-1") for n, v in scope["headers"]}
            state: dict[str, Any] = scope.setdefault("state", {})
            member = member_from_headers(headers)
            if member is not None:
                state["member"] = member
            if headers.get("x-platform-admin") == "true":
                state["is_platform_admin"] = True
        await super().__call__(scope, receive, send)


@pytest.fixture(autouse=True)
def _header_identity(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Give every app built by `create_app` the header identity, unless the module opts out."""
    if not getattr(request.module, "REAL_AUTH", False):
        monkeypatch.setattr(app_main, "AuthMiddleware", HeaderIdentityAuthMiddleware)
    yield
