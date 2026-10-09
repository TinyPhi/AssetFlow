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
