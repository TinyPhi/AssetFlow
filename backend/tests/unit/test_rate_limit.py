# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Unit tests for rate limiting (§B7.2, §C1.5, M1.3-T6)."""

from __future__ import annotations

import pytest
from starlette.requests import Request

from app.core.problems import RateLimitedError
from app.core.rate_limit import InMemoryRateLimitStore, RateLimiter, get_client_identifier


async def test_in_memory_rate_limit_store_allow_and_block() -> None:
    store = InMemoryRateLimitStore()
    key = "test:client-1"

    # Allow 3 requests in a 10s window
    allowed1, retry1 = await store.hit(key, limit=3, window_seconds=10)
    assert allowed1
    assert retry1 == 0

    allowed2, _ = await store.hit(key, limit=3, window_seconds=10)
    assert allowed2

    allowed3, _ = await store.hit(key, limit=3, window_seconds=10)
    assert allowed3

    # 4th request exceeds limit
    allowed4, retry4 = await store.hit(key, limit=3, window_seconds=10)
    assert not allowed4
    assert retry4 > 0


async def test_rate_limiter_dependency_raises() -> None:
    store = InMemoryRateLimitStore()
    limiter = RateLimiter(times=2, seconds=5, store=store)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/assets",
        "headers": [(b"x-forwarded-for", b"198.51.100.1")],
        "client": ("127.0.0.1", 12345),
    }
    req = Request(scope)

    # First two should succeed
    await limiter(req)
    await limiter(req)

    # Third should raise RateLimitedError with Retry-After
    with pytest.raises(RateLimitedError) as exc_info:
        await limiter(req)

    err = exc_info.value
    assert err.status_code == 429
    assert err.code == "rate_limit.exceeded"
    assert "Retry-After" in err.headers
    assert int(err.headers["Retry-After"]) >= 1


async def test_client_identifier_resolution() -> None:
    # Authenticated user takes precedence
    scope1 = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"x-forwarded-for", b"203.0.113.195")],
        "state": {"member_id": "mem-42"},
    }
    req1 = Request(scope1)
    req1.state.member_id = "mem-42"
    assert get_client_identifier(req1) == "member:mem-42"

    # Forwarded IP when unauthenticated
    scope2 = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"x-forwarded-for", b"203.0.113.195, 10.0.0.1")],
    }
    req2 = Request(scope2)
    assert get_client_identifier(req2) == "ip:203.0.113.195"


async def test_client_identifier_ignores_invalid_forwarded_ip() -> None:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"x-forwarded-for", b"not-an-ip")],
        "client": ("192.0.2.7", 12345),
    }
    assert get_client_identifier(Request(scope)) == "ip:192.0.2.7"
