# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Circuit breaker for one channel installation (§B6.1 rule 9).

Opens after 5 consecutive failures; after 30 s it lets exactly one trial call through
(half-open): a success closes it, a failure opens it again for another 30 s. While open, the sender
leaves deliveries queued and does not count the skipped attempt towards dead-lettering. State is
per worker process (one breaker per organization and installation); a second worker keeps its own,
which only means each notices an outage by itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

__all__ = ["CircuitBreaker", "CircuitRegistry", "CircuitState"]

DEFAULT_FAILURE_THRESHOLD = 5
DEFAULT_OPEN_SECONDS = 30


class CircuitState(StrEnum):
    """Where a breaker is right now."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    """Consecutive-failure breaker; the caller passes the current time (`app.core.clock.now()`)."""

    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD
    open_seconds: int = DEFAULT_OPEN_SECONDS
    consecutive_failures: int = 0
    opened_at: datetime | None = None
    trial_in_flight: bool = False

    def state(self, now: datetime) -> CircuitState:
        """Closed, open (waiting out `open_seconds`), or half-open (a trial may run)."""
        if self.opened_at is None:
            return CircuitState.CLOSED
        if now - self.opened_at < timedelta(seconds=self.open_seconds):
            return CircuitState.OPEN
        return CircuitState.HALF_OPEN

    def allow(self, now: datetime) -> bool:
        """True when a call may be made now; in half-open state only the first caller gets a trial."""
        state = self.state(now)
        if state is CircuitState.CLOSED:
            return True
        if state is CircuitState.OPEN or self.trial_in_flight:
            return False
        self.trial_in_flight = True
        return True

    def retry_after(self, now: datetime) -> datetime:
        """The earliest time a trial may run (now, when the breaker is not open)."""
        if self.opened_at is None:
            return now
        return max(now, self.opened_at + timedelta(seconds=self.open_seconds))

    def record_success(self) -> None:
        """A call worked: close the breaker."""
        self.consecutive_failures = 0
        self.opened_at = None
        self.trial_in_flight = False

    def record_failure(self, now: datetime) -> None:
        """A call failed in a way that says the destination is unhealthy."""
        self.consecutive_failures += 1
        was_trial = self.trial_in_flight
        self.trial_in_flight = False
        if was_trial or self.consecutive_failures >= self.failure_threshold:
            self.opened_at = now

    def release_trial(self) -> None:
        """A trial was granted but no call was made (for example the row vanished)."""
        self.trial_in_flight = False


class CircuitRegistry:
    """One `CircuitBreaker` per (organization, installation)."""

    def __init__(
        self, failure_threshold: int = DEFAULT_FAILURE_THRESHOLD, open_seconds: int = DEFAULT_OPEN_SECONDS
    ) -> None:
        self._failure_threshold = failure_threshold
        self._open_seconds = open_seconds
        self._breakers: dict[tuple[UUID, UUID], CircuitBreaker] = {}

    def get(self, organization_id: UUID, installation_id: UUID) -> CircuitBreaker:
        """The breaker for this installation, created closed on first use."""
        key = (organization_id, installation_id)
        if key not in self._breakers:
            self._breakers[key] = CircuitBreaker(self._failure_threshold, self._open_seconds)
        return self._breakers[key]

    def health(self, organization_id: UUID, installation_id: UUID, now: datetime) -> dict[str, object]:
        """`health()` fragment for a channel: state and consecutive failures, nothing else."""
        breaker = self.get(organization_id, installation_id)
        return {
            "circuit": breaker.state(now).value,
            "consecutive_failures": breaker.consecutive_failures,
        }
