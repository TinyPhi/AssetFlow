# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Application rate limiting (§B7.2, §C1.5, M1.3-T6).

Implements sliding window counters for rate limiting with RFC 9457
429 Problem Details responses and `Retry-After` headers.
"""

from __future__ import annotations

import asyncio
import ipaddress
import time
from collections import defaultdict, deque
from collections.abc import Iterable

from fastapi import Request

from app.core.problems import RateLimitedError


class InMemoryRateLimitStore:
    """Thread-safe sliding window rate limit counter in memory."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def hit(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        """Record a hit for `key`.

        Returns:
            (allowed: bool, retry_after_seconds: int)
        """
        async with self._lock:
            now = time.monotonic()
            window_start = now - window_seconds
            timestamps = self._hits[key]

            # Evict timestamps outside the sliding window
            while timestamps and timestamps[0] <= window_start:
                timestamps.popleft()

            if len(timestamps) >= limit:
                # Earliest timestamp indicates when the oldest slot will free up
                oldest = timestamps[0]
                retry_after = max(1, int(oldest + window_seconds - now))
                return False, retry_after

            timestamps.append(now)
            return True, 0

    async def reset(self) -> None:
        """Clear all stored hits (used in tests)."""
        async with self._lock:
            self._hits.clear()


# Default global store
default_rate_limit_store = InMemoryRateLimitStore()


type ProxyNetworks = tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]


def parse_proxy_cidrs(cidrs: Iterable[str]) -> ProxyNetworks:
    """Parse configured proxy networks (`platform.trusted_proxy_cidrs`); a bad entry raises ValueError."""
    return tuple(ipaddress.ip_network(c, strict=False) for c in cidrs)


def _in_networks(ip: ipaddress.IPv4Address | ipaddress.IPv6Address, networks: ProxyNetworks) -> bool:
    return any(ip in network for network in networks)


def _forwarded_client_ip(request: Request, trusted: ProxyNetworks) -> str | None:
    """The client IP from X-Forwarded-For, trusted only when the TCP peer is a configured proxy.

    Walks the header from the right, skipping hops that are themselves trusted proxies, and returns
    the first untrusted hop (the one a trusted proxy actually saw). Entries to its left are
    client-controlled and never read. Returns None when the header cannot be trusted.
    """
    if not trusted or not request.client or not request.client.host:
        return None
    try:
        peer = ipaddress.ip_address(request.client.host)
    except ValueError:
        return None
    header = request.headers.get("X-Forwarded-For")
    if not header or not _in_networks(peer, trusted):
        return None
    for raw in reversed(header.split(",")):
        try:
            hop = ipaddress.ip_address(raw.strip())
        except ValueError:
            return None
        if not _in_networks(hop, trusted):
            return str(hop)
    return None


def get_client_identifier(request: Request, trusted_proxies: ProxyNetworks = ()) -> str:
    """Derive the client identifier: authenticated member, else IP (forwarded only via trusted proxies)."""
    user_id = getattr(request.state, "member_id", None) or getattr(request.state, "user_id", None)
    if user_id:
        return f"member:{user_id}"

    forwarded = _forwarded_client_ip(request, trusted_proxies)
    if forwarded is not None:
        return f"ip:{forwarded}"  # nosemgrep: directly-returned-format-string (non-Flask)

    if request.client and request.client.host:
        return f"ip:{request.client.host}"

    return "unknown"


def _route_template(request: Request) -> str:
    """The matched route's path template (`/assets/{asset_id}`), so one route is one key family."""
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    return template if isinstance(template, str) else request.url.path


class RateLimiter:
    """FastAPI dependency for endpoint rate limiting (§C1.5, M1.3-T6)."""

    def __init__(
        self,
        times: int = 100,
        seconds: int = 60,
        store: InMemoryRateLimitStore | None = None,
        key_prefix: str = "rl",
        trusted_proxy_cidrs: Iterable[str] | None = None,
    ) -> None:
        self.times = times
        self.seconds = seconds
        self.store = store or default_rate_limit_store
        self.key_prefix = key_prefix
        self._trusted = parse_proxy_cidrs(trusted_proxy_cidrs) if trusted_proxy_cidrs is not None else None

    def _trusted_proxies(self, request: Request) -> ProxyNetworks:
        """Explicit constructor value, else `platform.trusted_proxy_cidrs` of the running app's config."""
        if self._trusted is not None:
            return self._trusted
        config = (
            getattr(getattr(request.app.state, "config", None), "platform", None)
            if "app" in request.scope
            else None
        )
        cidrs = getattr(config, "trusted_proxy_cidrs", None)
        return parse_proxy_cidrs(cidrs) if cidrs else ()

    async def __call__(self, request: Request) -> None:
        identifier = get_client_identifier(request, self._trusted_proxies(request))
        key = f"{self.key_prefix}:{_route_template(request)}:{identifier}"
        allowed, retry_after = await self.store.hit(key, self.times, self.seconds)
        if not allowed:
            raise RateLimitedError(
                f"Rate limit exceeded: {self.times} requests per {self.seconds} seconds.",
                retry_after_seconds=retry_after,
            )
