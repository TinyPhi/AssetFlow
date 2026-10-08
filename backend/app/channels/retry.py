# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""What counts as retryable, and how long to wait (§B6.3 rule 5, §C6.7, §C8.4).

Retryable: timeouts, connection errors and 5xx. Not retryable: every 4xx (the request itself is
wrong, sending it again changes nothing) and a refused egress (a configuration problem). 3 attempts
in all; the delay after attempt n is `BACKOFF_SECONDS[n - 1]`, so after the 1st failure 1 s, after
the 2nd 4 s. The 16 s entry is the delay that would follow a 3rd failure; a 3rd failure instead
dead-letters the delivery, so it is never waited. Error codes here are codes, never a server
message (which may echo an address).
"""

from __future__ import annotations

import httpx

from app.channels.base import DeliveryResult
from app.core.problems import ChannelEgressDeniedError, SecretsUnavailableError

__all__ = [
    "BACKOFF_SECONDS",
    "MAX_ATTEMPTS",
    "backoff_seconds",
    "failure_from_exception",
    "failure_from_status",
]

MAX_ATTEMPTS = 3
BACKOFF_SECONDS: tuple[int, ...] = (1, 4, 16)


def backoff_seconds(attempts_made: int) -> int:
    """Seconds to wait after `attempts_made` failed attempts (1-based)."""
    index = min(max(attempts_made, 1), len(BACKOFF_SECONDS)) - 1
    return BACKOFF_SECONDS[index]


def failure_from_status(status_code: int, latency_ms: int | None = None) -> DeliveryResult:
    """A failed result for an HTTP response with `status_code` (5xx retries, 4xx does not)."""
    return DeliveryResult(
        delivered=False,
        error_code=f"http_{status_code}",
        latency_ms=latency_ms,
        retryable=status_code >= 500,
    )


def failure_from_exception(exc: BaseException, latency_ms: int | None = None) -> DeliveryResult:
    """A failed result for an exception a send raised (never carries the exception's message)."""
    if isinstance(exc, ChannelEgressDeniedError):
        return DeliveryResult(False, ChannelEgressDeniedError.code, latency_ms, retryable=False)
    if isinstance(exc, httpx.TimeoutException | TimeoutError):
        return DeliveryResult(False, "timeout", latency_ms, retryable=True)
    if isinstance(exc, httpx.TransportError | OSError):
        return DeliveryResult(False, "connection_error", latency_ms, retryable=True)
    if isinstance(exc, SecretsUnavailableError):
        return DeliveryResult(False, SecretsUnavailableError.code, latency_ms, retryable=True)
    return DeliveryResult(False, "unexpected_error", latency_ms, retryable=True)
