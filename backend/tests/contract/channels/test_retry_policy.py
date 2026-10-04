# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Retry and circuit-breaker rules every channel is held to (§B6.3 rule 5, §B6.1 rule 9, §C6.7, §C8.4)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from app.channels.circuit import CircuitBreaker, CircuitRegistry, CircuitState
from app.channels.retry import (
    BACKOFF_SECONDS,
    MAX_ATTEMPTS,
    backoff_seconds,
    failure_from_exception,
    failure_from_status,
)
from app.core.problems import ChannelEgressDeniedError, SecretsUnavailableError

T0 = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize("status", [500, 502, 503, 504, 599])
def test_5xx_is_retried(status: int) -> None:
    result = failure_from_status(status)
    assert not result.delivered
    assert result.retryable
    assert result.error_code == f"http_{status}"


@pytest.mark.parametrize("status", [400, 401, 403, 404, 410, 422, 429, 499])
def test_every_4xx_is_not_retried(status: int) -> None:
    assert not failure_from_status(status).retryable


@pytest.mark.parametrize(
    ("exc", "code", "retryable"),
    [
        (httpx.ReadTimeout("secret-host.internal slow"), "timeout", True),
        (TimeoutError(), "timeout", True),
        (httpx.ConnectError("could not reach 10.0.0.9"), "connection_error", True),
        (ConnectionResetError(), "connection_error", True),
        (SecretsUnavailableError(), "platform.secrets_unavailable", True),
        (ChannelEgressDeniedError(), "channel.egress_denied", False),
        (RuntimeError("boom with an address 10.0.0.9"), "unexpected_error", True),
    ],
)
def test_exceptions_map_to_a_code_and_never_carry_the_message(
    exc: BaseException, code: str, retryable: bool
) -> None:
    result = failure_from_exception(exc)
    assert (result.error_code, result.retryable, result.delivered) == (code, retryable, False)
    assert "10.0.0.9" not in repr(result)
    assert "internal" not in repr(result)


def test_three_attempts_with_exponential_backoff() -> None:
    assert MAX_ATTEMPTS == 3
    assert BACKOFF_SECONDS == (1, 4, 16)
    assert [backoff_seconds(n) for n in (1, 2, 3)] == [1, 4, 16]
    assert backoff_seconds(0) == 1
    assert backoff_seconds(99) == 16


def test_the_circuit_opens_after_five_consecutive_failures() -> None:
    breaker = CircuitBreaker()
    for _ in range(4):
        breaker.record_failure(T0)
        assert breaker.allow(T0)
    breaker.record_failure(T0)
    assert breaker.state(T0) is CircuitState.OPEN
    assert not breaker.allow(T0 + timedelta(seconds=29))


def test_a_success_resets_the_count() -> None:
    breaker = CircuitBreaker()
    for _ in range(4):
        breaker.record_failure(T0)
    breaker.record_success()
    for _ in range(4):
        breaker.record_failure(T0)
    assert breaker.state(T0) is CircuitState.CLOSED


def test_half_open_lets_exactly_one_trial_through() -> None:
    breaker = CircuitBreaker()
    for _ in range(5):
        breaker.record_failure(T0)
    later = T0 + timedelta(seconds=30)
    assert breaker.state(later) is CircuitState.HALF_OPEN
    assert breaker.allow(later)
    assert not breaker.allow(later)  # the trial is in flight


def test_a_successful_trial_closes_and_a_failed_one_reopens() -> None:
    breaker = CircuitBreaker()
    for _ in range(5):
        breaker.record_failure(T0)
    later = T0 + timedelta(seconds=31)
    assert breaker.allow(later)
    breaker.record_failure(later)
    assert breaker.state(later) is CircuitState.OPEN
    assert breaker.retry_after(later) == later + timedelta(seconds=30)

    again = later + timedelta(seconds=31)
    assert breaker.allow(again)
    breaker.record_success()
    assert breaker.state(again) is CircuitState.CLOSED
    assert breaker.allow(again)


def test_a_released_trial_can_be_granted_again() -> None:
    breaker = CircuitBreaker()
    for _ in range(5):
        breaker.record_failure(T0)
    later = T0 + timedelta(seconds=30)
    assert breaker.allow(later)
    breaker.release_trial()
    assert breaker.allow(later)


def test_each_installation_has_its_own_breaker_and_reports_it() -> None:
    registry = CircuitRegistry()
    org_a, org_b, installation = uuid4(), uuid4(), uuid4()
    for _ in range(5):
        registry.get(org_a, installation).record_failure(T0)
    assert registry.health(org_a, installation, T0) == {"circuit": "open", "consecutive_failures": 5}
    assert registry.health(org_b, installation, T0) == {"circuit": "closed", "consecutive_failures": 0}


def test_the_thresholds_can_be_overridden() -> None:
    breaker = CircuitBreaker(failure_threshold=2, open_seconds=5)
    breaker.record_failure(T0)
    breaker.record_failure(T0)
    assert breaker.state(T0 + timedelta(seconds=4)) is CircuitState.OPEN
    assert breaker.state(T0 + timedelta(seconds=5)) is CircuitState.HALF_OPEN
