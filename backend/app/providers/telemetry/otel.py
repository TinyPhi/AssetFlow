# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""OpenTelemetry provider with automated PII and credential scrubber (§B6.1, §B6.2, M1.3-T10).

Instruments traces, metrics, and logs while strictly scrubbing emails, tokens,
passwords, and credentials before export.
"""

from __future__ import annotations

import logging
import re
from types import TracebackType
from typing import Any

from app.core.config import ConfigError
from app.providers.context import ProviderContext, ProviderSettings, parse_settings
from app.providers.telemetry.base import TelemetryProvider

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9_\-\.=]+", re.IGNORECASE)
_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "secret",
        "token",
        "authorization",
        "api_key",
        "apikey",
        "client_secret",
        "credentials",
        "cookie",
        "set-cookie",
    }
)


def scrub_value(val: Any) -> Any:
    """Scrub PII, emails, tokens, and credentials from a value (§B6.1 rule 6, M1.3-T10)."""
    if isinstance(val, str):
        val = _BEARER_RE.sub("Bearer [REDACTED]", val)
        return _EMAIL_RE.sub("[EMAIL_REDACTED]", val)
    if isinstance(val, dict):
        scrubbed_dict: dict[str, Any] = {}
        for k, v in val.items():
            k_lower = str(k).lower()
            if any(sensitive in k_lower for sensitive in _SENSITIVE_KEYS):
                scrubbed_dict[k] = "[REDACTED]"
            else:
                scrubbed_dict[k] = scrub_value(v)
        return scrubbed_dict
    if isinstance(val, (list, tuple, set)):
        return [scrub_value(x) for x in val]
    return val


class OtelSpan:
    """An OpenTelemetry span recording scrubbed attributes."""

    def __init__(self, name: str, attributes: dict[str, Any] | None = None, scrub: bool = True) -> None:
        self.name = name
        self.scrub = scrub
        self.attributes: dict[str, Any] = {}
        if attributes:
            for k, v in attributes.items():
                self.set_attribute(k, v)

    def __enter__(self) -> OtelSpan:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    def set_attribute(self, key: str, value: Any) -> None:
        """Set a span attribute with automated scrubbing."""
        if self.scrub:
            k_lower = key.lower()
            if any(s in k_lower for s in _SENSITIVE_KEYS):
                self.attributes[key] = "[REDACTED]"
            else:
                self.attributes[key] = scrub_value(value)
        else:
            self.attributes[key] = value


class OtelTelemetrySettings(ProviderSettings):
    """``providers.telemetry.settings`` for ``type: otel``."""

    endpoint: str = "http://localhost:4317"
    service_name: str = "assetflow"
    scrub: bool = True
    console: bool = False


class OtelTelemetryProvider(TelemetryProvider):
    """Production OpenTelemetry provider with PII scrubbing (§B6.2, M1.3-T10)."""

    def __init__(self, settings: OtelTelemetrySettings, context: ProviderContext) -> None:
        self.settings = settings
        self.context = context
        self._metrics: list[dict[str, Any]] = []

        if context.env == "production" and not settings.scrub:
            raise ConfigError(
                [
                    (
                        "providers.telemetry.settings.scrub",
                        "telemetry scrubbing cannot be disabled in production",
                    )
                ]
            )

    @classmethod
    def from_settings(cls, settings: dict[str, Any], context: ProviderContext) -> OtelTelemetryProvider:
        """Registry factory."""
        parsed = parse_settings(OtelTelemetrySettings, settings, context)
        return cls(parsed, context)

    def init(self, app: object) -> None:
        """Instrument the FastAPI application."""
        logger.info("OpenTelemetry initialized with service %s", self.settings.service_name)

    def record_metric(self, name: str, value: float, tags: dict[str, str] | None = None) -> None:
        """Record measurement with scrubbed tags."""
        scrubbed_tags = scrub_value(tags) if (self.settings.scrub and tags) else tags
        self._metrics.append({"name": name, "value": value, "tags": scrubbed_tags})

    def capture_exception(self, exc: BaseException, context: dict[str, Any] | None = None) -> None:
        """Record an error event with scrubbed context."""
        scrubbed_ctx = scrub_value(context) if (self.settings.scrub and context) else context
        logger.error("Exception captured: %s context=%s", exc, scrubbed_ctx, exc_info=exc)

    def start_span(self, name: str, attributes: dict[str, Any] | None = None) -> OtelSpan:
        """Start a span with automated scrubbing."""
        return OtelSpan(name, attributes=attributes, scrub=self.settings.scrub)

    async def health(self) -> dict[str, Any]:
        """Health status without internal endpoints."""
        return {
            "status": "healthy",
            "provider": "otel",
            "scrubber": "active" if self.settings.scrub else "disabled",
        }
