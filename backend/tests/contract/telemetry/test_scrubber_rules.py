# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Scrubber rules: PII shapes, whole-word keys, exception text and the root log filter (AF-035/036/048)."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

import app.providers.telemetry.scrub as scrub_module
from app.providers.context import ProviderContext
from app.providers.telemetry.noop import NoOpTelemetryProvider
from app.providers.telemetry.otel import OtelTelemetryProvider
from app.providers.telemetry.scrub import is_sensitive_key, scrub_value

JWT = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjMifQ.c2lnbmF0dXJl"


@pytest.mark.parametrize(
    ("raw", "leaked"),
    [
        ("call +91 98765 43210 now", "98765"),
        ("call (020) 7946-0958 now", "7946"),
        ("from 192.168.10.25 failed", "192.168.10.25"),
        ("from 2001:db8::8a2e:370:7334 failed", "8a2e"),
        (f"token {JWT} seen", "c2lnbmF0dXJl"),
        ("key sk_" + "live_4eC39HqLyjWDarjtT1zdp7dc used", "4eC39Hq"),
        ("blob Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MGFiY2RlZmdoaWo end", "Zm9vYmFy"),
    ],
)
def test_scrubber_redacts_pii_shapes(raw: str, leaked: str) -> None:
    assert leaked not in scrub_value(raw)


@pytest.mark.parametrize(
    "safe",
    [
        "order 0192f000-0000-7000-8000-000000000002",
        "at 2026-10-07 12:30:45 UTC",
        "version 1.2.3 build 300.1.1.1",
        "count 1234567",
    ],
)
def test_scrubber_keeps_ordinary_text(safe: str) -> None:
    assert scrub_value(safe) == safe


@pytest.mark.parametrize("key", ["access_token", "apiKey", "API_KEY", "Set-Cookie", "db.password", "secrets"])
def test_sensitive_keys_match_whole_words(key: str) -> None:
    assert is_sensitive_key(key)


@pytest.mark.parametrize("key", ["tokenizer", "monkey", "secretary", "keyboard", "order"])
def test_sensitive_keys_ignore_substrings(key: str) -> None:
    assert not is_sensitive_key(key)


@pytest.fixture
def restore_record_factory() -> Iterator[None]:
    factory = logging.getLogRecordFactory()
    yield
    logging.setLogRecordFactory(factory)
    scrub_module._factory_installed = False


@pytest.mark.parametrize("cls", [OtelTelemetryProvider, NoOpTelemetryProvider])
def test_root_log_filter_scrubs_exception_text(
    cls: type, caplog: pytest.LogCaptureFixture, restore_record_factory: None
) -> None:
    ctx = ProviderContext(env="test", pillar="telemetry", base_dir=Path.cwd())
    provider = cls.from_settings({"scrub": True}, ctx)
    provider.init(object())
    log = logging.getLogger("assetflow.somewhere.else")

    with caplog.at_level(logging.ERROR):
        try:
            raise ValueError("bad login for ops@example.org from 10.1.2.3 with " + JWT)
        except ValueError:
            log.exception("failed for %s", "ops@example.org")
        if cls is OtelTelemetryProvider:
            provider.capture_exception(ValueError("secret ops@example.org 10.1.2.3"), {"password": "x"})

    text = caplog.text
    for leaked in ("ops@example.org", "10.1.2.3", "c2lnbmF0dXJl"):
        assert leaked not in text
    assert "[EMAIL_REDACTED]" in text
