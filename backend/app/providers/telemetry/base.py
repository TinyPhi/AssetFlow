# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""TelemetryProvider interface (§B6.1, §B6.2), INTERFACE_VERSION 1.0.

Implementations (``otel``, ``noop`` or a third-party entry point) pass the shared suite in
``tests/contract/telemetry/``.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any


class TelemetryProvider(ABC):
    """Tracing, metrics and logging provider."""

    INTERFACE_VERSION: str = "1.0"

    @property
    def name(self) -> str:
        """Provider implementation identifier."""
        return self.__class__.__name__

    async def aclose(self) -> None:  # noqa: B027 - optional hook with a no-op default
        """Release held resources (connections, clients). The default holds none."""

    @property
    def logger(self) -> logging.Logger:
        """Logger for AssetFlow code (§B6.2 ``logger``)."""
        return logging.getLogger("assetflow")

    @abstractmethod
    def init(self, app: object) -> None:
        """Instrument the application (§B6.2 ``init(app)``)."""

    @abstractmethod
    def record_metric(self, name: str, value: float, tags: dict[str, str] | None = None) -> None:
        """Record one measurement."""

    @abstractmethod
    def capture_exception(self, exc: BaseException, context: dict[str, Any] | None = None) -> None:
        """Record an error event."""

    @abstractmethod
    def start_span(self, name: str, attributes: dict[str, Any] | None = None) -> Any:
        """Start a span; the result is a context manager with ``set_attribute``."""

    @abstractmethod
    async def health(self) -> dict[str, Any]:
        """Return ``{"status": ...}``."""
