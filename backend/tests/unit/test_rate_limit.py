# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Unit tests for rate limiting (§B7.2, §C1.5, M1.3-T6)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.core.problems import RateLimitedError
from app.core.rate_limit import InMemoryRateLimitStore, RateLimiter, get_client_identifier, parse_proxy_cidrs


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
    req2 = Request({**scope2, "client": ("10.0.0.1", 4000)})
    assert get_client_identifier(req2, parse_proxy_cidrs(["10.0.0.0/8"])) == "ip:203.0.113.195"


def _request(xff: bytes | None, peer: str, path: str = "/") -> Request:
    headers = [(b"x-forwarded-for", xff)] if xff is not None else []
    return Request({"type": "http", "method": "GET", "path": path, "headers": headers, "client": (peer, 1)})


def test_spoofed_forwarded_header_from_untrusted_peer_is_ignored() -> None:
    trusted = parse_proxy_cidrs(["10.0.0.0/8"])
    assert get_client_identifier(_request(b"1.2.3.4", "198.51.100.9"), trusted) == "ip:198.51.100.9"
    # No trusted proxies configured: the header is never read.
    assert get_client_identifier(_request(b"1.2.3.4", "10.0.0.2")) == "ip:10.0.0.2"


def test_forwarded_header_takes_rightmost_untrusted_hop() -> None:
    trusted = parse_proxy_cidrs(["10.0.0.0/8", "172.16.0.0/12"])
    # The client prepended a spoofed 1.2.3.4; the proxy appended the real 203.0.113.5.
    request = _request(b"1.2.3.4, 203.0.113.5, 172.16.0.3", "10.0.0.2")
    assert get_client_identifier(request, trusted) == "ip:203.0.113.5"


def test_forwarded_header_with_garbage_hop_falls_back_to_peer() -> None:
    trusted = parse_proxy_cidrs(["10.0.0.0/8"])
    assert get_client_identifier(_request(b"1.2.3.4, junk", "10.0.0.2"), trusted) == "ip:10.0.0.2"


async def test_rate_limit_key_uses_route_template_not_concrete_path() -> None:
    store = InMemoryRateLimitStore()
    limiter = RateLimiter(times=2, seconds=60, store=store)

    def request_for(asset_id: str) -> Request:
        request = _request(None, "192.0.2.1", path=f"/assets/{asset_id}")
        request.scope["route"] = SimpleNamespace(path="/assets/{asset_id}")
        return request

    await limiter(request_for("a"))
    await limiter(request_for("b"))
    with pytest.raises(RateLimitedError):
        await limiter(request_for("c"))


async def test_client_identifier_ignores_invalid_forwarded_ip() -> None:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"x-forwarded-for", b"not-an-ip")],
        "client": ("192.0.2.7", 12345),
    }
    assert get_client_identifier(Request(scope)) == "ip:192.0.2.7"
