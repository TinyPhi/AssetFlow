# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The asset and component routers rate-limit per caller (PR #290 review, merge blocker).

Component attach/detach take a per-org advisory lock (`ComponentRepository.lock_attachments`);
with no rate limit, a caller could hold that lock open repeatedly at near-zero cost. The main
assets router had no rate limit at all. Both now carry a member-keyed sliding-window limiter,
mounted the same way as every other route that needs one (`app.core.rate_limit`).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.core.problems import RateLimitedError
from app.modules.assets.components.router import _components_rate_limit
from app.modules.assets.router import _assets_rate_limit
from app.modules.assets.saved_views import _saved_views_rate_limit
from app.modules.assets.saved_views import router as saved_views_router


def _request(member_id: str | None, path: str = "/api/v1/assets") -> Request:
    scope: dict[str, object] = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [],
        "client": ("127.0.0.1", 12345),
    }
    req = Request(scope)
    if member_id is not None:
        req.state.member = SimpleNamespace(member_id=member_id)
    return req


async def test_assets_router_rate_limits_a_single_member() -> None:
    req = _request("member-a")
    for _ in range(180):
        await _assets_rate_limit(req)
    with pytest.raises(RateLimitedError):
        await _assets_rate_limit(req)


async def test_assets_router_rate_limit_is_scoped_per_member() -> None:
    exhausted = _request("member-b")
    for _ in range(180):
        await _assets_rate_limit(exhausted)
    with pytest.raises(RateLimitedError):
        await _assets_rate_limit(exhausted)

    unrelated = _request("member-c")
    await _assets_rate_limit(unrelated)  # does not raise


async def test_components_router_rate_limits_a_single_member() -> None:
    req = _request("member-d", path="/api/v1/assets/00000000-0000-0000-0000-000000000001/components")
    for _ in range(60):
        await _components_rate_limit(req)
    with pytest.raises(RateLimitedError):
        await _components_rate_limit(req)


async def test_component_budget_is_shared_across_assets_and_routes() -> None:
    """Spreading calls over many asset ids and over list/attach/detach must not multiply the
    budget: the attach/detach lock is per organization, so the limit has to be per member."""
    paths = [
        f"/api/v1/assets/00000000-0000-0000-0000-{i:012d}/components"
        + ("" if i % 2 else f"/00000000-0000-0000-0000-{i + 1:012d}/detach")
        for i in range(60)
    ]
    for path in paths:  # 60 calls over 60 different asset ids and two route shapes
        await _components_rate_limit(_request("member-e", path=path))
    with pytest.raises(RateLimitedError):
        other_asset = "/api/v1/assets/11111111-1111-1111-1111-111111111111/components"
        await _components_rate_limit(_request("member-e", path=other_asset))


async def test_asset_budget_is_shared_across_asset_ids() -> None:
    for i in range(180):
        path = f"/api/v1/assets/00000000-0000-0000-0000-{i:012d}"
        await _assets_rate_limit(_request("member-f", path=path))
    with pytest.raises(RateLimitedError):
        await _assets_rate_limit(_request("member-f", path="/api/v1/assets/vocabulary"))


async def test_saved_views_router_rate_limits_a_single_member() -> None:
    """Every saved-view write adds an audit row and an outbox row (#352 review, M3)."""
    for i in range(60):
        path = f"/api/v1/asset-saved-views/00000000-0000-0000-0000-{i:012d}"
        await _saved_views_rate_limit(_request("member-g", path=path))
    with pytest.raises(RateLimitedError):
        await _saved_views_rate_limit(_request("member-g", path="/api/v1/asset-saved-views"))
    await _saved_views_rate_limit(_request("member-h", path="/api/v1/asset-saved-views"))


def test_saved_views_router_declares_the_rate_limit() -> None:
    calls = [d.dependency for d in saved_views_router.dependencies]
    assert _saved_views_rate_limit in calls
