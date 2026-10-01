# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for OpenTelemetry provider scrubber (§B6.1, §B6.2, M1.3-T10)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import ConfigError
from app.providers.context import ProviderContext
from app.providers.telemetry.otel import OtelTelemetryProvider, scrub_value


def test_scrub_value_pii_and_secrets() -> None:
    data = {
        "email": "technician.lead@example.org",
        "authorization": "Bearer eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjMifQ.abc",
        "password": "supersecretpassword123",
        "client_secret": "bao_secret_token",
        "nested": {
            "contact": "Contact john.doe@acme.com for support",
            "api_key": "not-a-real-key",
            "safe_counter": 42,
        },
        "tags": ["token: 123", "normal_tag"],
    }

    scrubbed = scrub_value(data)

    assert scrubbed["email"] == "[EMAIL_REDACTED]"
    assert scrubbed["authorization"] == "[REDACTED]"
    assert scrubbed["password"] == "[REDACTED]"
    assert scrubbed["client_secret"] == "[REDACTED]"
    assert scrubbed["nested"]["contact"] == "Contact [EMAIL_REDACTED] for support"
    assert scrubbed["nested"]["api_key"] == "[REDACTED]"
    assert scrubbed["nested"]["safe_counter"] == 42


def test_otel_span_scrubs_attributes() -> None:
    ctx = ProviderContext(env="test", pillar="telemetry", base_dir=Path.cwd())
    provider = OtelTelemetryProvider.from_settings({"scrub": True}, ctx)

    with provider.start_span("dispatch_order") as span:
        span.set_attribute("user.email", "admin@example.org")
        span.set_attribute("secret_key", "super-secret-transit-key")
        span.set_attribute("order.id", "0192f000-0000-7000-8000-000000000002")

    assert span.attributes["user.email"] == "[EMAIL_REDACTED]"
    assert span.attributes["secret_key"] == "[REDACTED]"
    assert span.attributes["order.id"] == "0192f000-0000-7000-8000-000000000002"


def test_otel_production_guard_refuses_disabled_scrubber() -> None:
    ctx = ProviderContext(env="production", pillar="telemetry", base_dir=Path.cwd())
    with pytest.raises(ConfigError) as exc_info:
        OtelTelemetryProvider.from_settings({"scrub": False}, ctx)

    assert "telemetry scrubbing cannot be disabled in production" in str(exc_info.value)
