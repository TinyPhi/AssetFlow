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


def get_client_identifier(request: Request) -> str:
    """Derive client identifier from request state, forwarded headers, or client IP."""
    # Check if request has an authenticated member or principal
    user_id = getattr(request.state, "member_id", None) or getattr(request.state, "user_id", None)
    if user_id:
        return f"member:{user_id}"

    # Forwarded headers (e.g. from nginx edge proxy)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        try:
            client_ip = ipaddress.ip_address(forwarded.split(",")[0].strip())
        except ValueError:
            client_ip = None
        if client_ip is not None:
            return f"ip:{client_ip}"  # nosemgrep: directly-returned-format-string (non-Flask)

    if request.client and request.client.host:
        return f"ip:{request.client.host}"

    return "unknown"


class RateLimiter:
    """FastAPI dependency for endpoint rate limiting (§C1.5, M1.3-T6)."""

    def __init__(
        self,
        times: int = 100,
        seconds: int = 60,
        store: InMemoryRateLimitStore | None = None,
        key_prefix: str = "rl",
    ) -> None:
        self.times = times
        self.seconds = seconds
        self.store = store or default_rate_limit_store
        self.key_prefix = key_prefix

    async def __call__(self, request: Request) -> None:
        identifier = get_client_identifier(request)
        key = f"{self.key_prefix}:{request.url.path}:{identifier}"
        allowed, retry_after = await self.store.hit(key, self.times, self.seconds)
        if not allowed:
            raise RateLimitedError(
                f"Rate limit exceeded: {self.times} requests per {self.seconds} seconds.",
                retry_after_seconds=retry_after,
            )
