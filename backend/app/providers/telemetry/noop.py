# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""``noop`` telemetry provider: the fallback (§B6.2). Drops every measurement and span."""

from __future__ import annotations

from types import TracebackType
from typing import Any

from app.providers.context import ProviderContext, ProviderSettings, parse_settings
from app.providers.telemetry.base import TelemetryProvider
from app.providers.telemetry.scrub import install_root_log_filter


class NoOpTelemetrySettings(ProviderSettings):
    """``providers.telemetry.settings`` for ``type: noop``. ``scrub`` is accepted for symmetry."""

    scrub: bool = True


class NoOpSpan:
    """A span that records nothing."""

    def __enter__(self) -> NoOpSpan:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    def set_attribute(self, key: str, value: Any) -> None:
        """Ignore the attribute."""


class NoOpTelemetryProvider(TelemetryProvider):
    """Drops all telemetry."""

    @classmethod
    def from_settings(cls, settings: dict[str, Any], context: ProviderContext) -> NoOpTelemetryProvider:
        """Registry factory."""
        parse_settings(NoOpTelemetrySettings, settings, context)
        return cls()

    def init(self, app: object) -> None:
        """Nothing to instrument; log records are still scrubbed."""
        install_root_log_filter()

    def record_metric(self, name: str, value: float, tags: dict[str, str] | None = None) -> None:
        """Drop the measurement."""

    def capture_exception(self, exc: BaseException, context: dict[str, Any] | None = None) -> None:
        """Drop the error event."""

    def start_span(self, name: str, attributes: dict[str, Any] | None = None) -> NoOpSpan:
        """Return a span that records nothing."""
        return NoOpSpan()

    async def health(self) -> dict[str, Any]:
        """Always healthy."""
        return {"status": "healthy", "provider": "noop"}
