# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""OpenTelemetry provider with automated PII and credential scrubber (§B6.1, §B6.2, M1.3-T10).

Instruments traces, metrics, and logs while strictly scrubbing emails, tokens,
passwords, and credentials before export.
"""

from __future__ import annotations

import importlib
import logging
from types import TracebackType
from typing import Any

from app.core.config import ConfigError
from app.providers.context import ProviderContext, ProviderSettings, parse_settings
from app.providers.telemetry.base import TelemetryProvider
from app.providers.telemetry.scrub import (
    REDACTED,
    install_root_log_filter,
    is_sensitive_key,
    scrub_exception,
    scrub_text,
    scrub_value,
)

logger = logging.getLogger(__name__)

__all__ = ["OtelSpan", "OtelTelemetryProvider", "OtelTelemetrySettings", "scrub_value"]


class OtelSpan:
    """A span recording scrubbed attributes; also feeds the OpenTelemetry SDK span when one is set."""

    def __init__(
        self,
        name: str,
        attributes: dict[str, Any] | None = None,
        scrub: bool = True,
        tracer: Any = None,
    ) -> None:
        self.name = name
        self.scrub = scrub
        self.attributes: dict[str, Any] = {}
        self._sdk_span: Any = tracer.start_span(name) if tracer is not None else None
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
        if self._sdk_span is not None:
            if exc is not None:
                self._sdk_span.set_attribute("exception.type", type(exc).__name__)
                self._sdk_span.set_attribute("exception.message", scrub_text(str(exc)))
            self._sdk_span.end()

    def set_attribute(self, key: str, value: Any) -> None:
        """Set a span attribute with automated scrubbing."""
        if self.scrub:
            value = REDACTED if is_sensitive_key(key) else scrub_value(value)
        self.attributes[key] = value
        if self._sdk_span is not None:
            self._sdk_span.set_attribute(
                key, value if isinstance(value, (str, bool, int, float)) else str(value)
            )


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
        self.tracer: Any = None
        self.meter: Any = None
        self._tracer_provider: Any = None
        self._meter_provider: Any = None
        self._histograms: dict[str, Any] = {}

        if context.is_guarded and not settings.scrub:
            raise ConfigError(
                [
                    (
                        "providers.telemetry.settings.scrub",
                        "telemetry scrubbing cannot be disabled outside development and test",
                    )
                ]
            )

    @classmethod
    def from_settings(cls, settings: dict[str, Any], context: ProviderContext) -> OtelTelemetryProvider:
        """Registry factory."""
        parsed = parse_settings(OtelTelemetrySettings, settings, context)
        return cls(parsed, context)

    def configure(self, *, span_exporter: Any = None, metric_reader: Any = None) -> bool:
        """Build the SDK TracerProvider and MeterProvider (OTLP unless exporters are given).

        Returns False, leaving the in-process recording only, when the ``otel`` extra is absent.
        The providers stay private to this object: no global OpenTelemetry state is replaced.
        """
        try:
            resources = importlib.import_module("opentelemetry.sdk.resources")
            trace_sdk = importlib.import_module("opentelemetry.sdk.trace")
            trace_export = importlib.import_module("opentelemetry.sdk.trace.export")
            metrics_sdk = importlib.import_module("opentelemetry.sdk.metrics")
            metrics_export = importlib.import_module("opentelemetry.sdk.metrics.export")
            if span_exporter is None:
                span_exporter = importlib.import_module(
                    "opentelemetry.exporter.otlp.proto.grpc.trace_exporter"
                ).OTLPSpanExporter(endpoint=self.settings.endpoint)
            if metric_reader is None:
                metric_reader = metrics_export.PeriodicExportingMetricReader(
                    importlib.import_module(
                        "opentelemetry.exporter.otlp.proto.grpc.metric_exporter"
                    ).OTLPMetricExporter(endpoint=self.settings.endpoint)
                )
        except ImportError:
            logger.warning("OpenTelemetry SDK not installed (extra 'otel'); telemetry is not exported")
            return False
        resource = resources.Resource.create({"service.name": self.settings.service_name})
        self._tracer_provider = trace_sdk.TracerProvider(resource=resource)
        self._tracer_provider.add_span_processor(trace_export.BatchSpanProcessor(span_exporter))
        self._meter_provider = metrics_sdk.MeterProvider(resource=resource, metric_readers=[metric_reader])
        self.tracer = self._tracer_provider.get_tracer("assetflow")
        self.meter = self._meter_provider.get_meter("assetflow")
        return True

    def init(self, app: object) -> None:
        """Start SDK export (when installed) and scrub every log record of the process."""
        if self.settings.scrub:
            install_root_log_filter()
        if self.configure():
            logger.info("OpenTelemetry export started for service %s", self.settings.service_name)

    def record_metric(self, name: str, value: float, tags: dict[str, str] | None = None) -> None:
        """Record measurement with scrubbed tags."""
        scrubbed_tags = scrub_value(tags) if (self.settings.scrub and tags) else tags
        self._metrics.append({"name": name, "value": value, "tags": scrubbed_tags})
        if self.meter is not None:
            if name not in self._histograms:
                self._histograms[name] = self.meter.create_histogram(name)
            self._histograms[name].record(value, attributes=scrubbed_tags or {})

    def capture_exception(self, exc: BaseException, context: dict[str, Any] | None = None) -> None:
        """Record an error event with scrubbed exception text and context."""
        scrubbed_ctx = scrub_value(context) if (self.settings.scrub and context) else context
        text = scrub_exception(exc) if self.settings.scrub else repr(exc)
        logger.error("Exception captured: %s context=%s", text, scrubbed_ctx)

    def start_span(self, name: str, attributes: dict[str, Any] | None = None) -> OtelSpan:
        """Start a span with automated scrubbing."""
        return OtelSpan(name, attributes=attributes, scrub=self.settings.scrub, tracer=self.tracer)

    async def aclose(self) -> None:
        """Flush and shut down the SDK providers."""
        for provider in (self._tracer_provider, self._meter_provider):
            if provider is not None:
                provider.force_flush()
                provider.shutdown()
        self._tracer_provider = self._meter_provider = None
        self.tracer = self.meter = None

    async def health(self) -> dict[str, Any]:
        """Health status without internal endpoints."""
        return {
            "status": "healthy",
            "provider": "otel",
            "scrubber": "active" if self.settings.scrub else "disabled",
        }
