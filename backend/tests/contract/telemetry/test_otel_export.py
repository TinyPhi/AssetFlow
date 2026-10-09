# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The otel provider exports real spans and metrics through the SDK (AF-019)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.providers.context import ProviderContext
from app.providers.telemetry.noop import NoOpTelemetryProvider
from app.providers.telemetry.otel import OtelTelemetryProvider

pytest.importorskip("opentelemetry.sdk.trace", reason="extra 'otel' not installed")

from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


def _provider() -> OtelTelemetryProvider:
    ctx = ProviderContext(env="test", pillar="telemetry", base_dir=Path.cwd())
    return OtelTelemetryProvider.from_settings({"service_name": "assetflow-test"}, ctx)


async def test_spans_and_metrics_reach_in_memory_exporters() -> None:
    exporter = InMemorySpanExporter()
    reader = InMemoryMetricReader()
    provider = _provider()
    assert provider.configure(span_exporter=exporter, metric_reader=reader)
    # Batch export is asynchronous; a simple processor makes the export observable at once.
    provider._tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))

    with provider.start_span("dispatch", {"user.email": "a@example.org", "order.id": "42"}):
        pass
    provider.record_metric("jobs.done", 3, {"queue": "default", "api_key": "k"})

    spans = exporter.get_finished_spans()
    assert [s.name for s in spans] == ["dispatch"]
    assert spans[0].attributes["user.email"] == "[EMAIL_REDACTED]"
    assert spans[0].attributes["order.id"] == "42"
    assert spans[0].resource.attributes["service.name"] == "assetflow-test"
    data = reader.get_metrics_data()
    names = [m.name for rm in data.resource_metrics for sm in rm.scope_metrics for m in sm.metrics]
    assert names == ["jobs.done"]
    await provider.aclose()


async def test_noop_stays_default_and_aclose_is_noop() -> None:
    await NoOpTelemetryProvider().aclose()
