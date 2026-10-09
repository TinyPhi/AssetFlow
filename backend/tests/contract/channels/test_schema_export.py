# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Settings schema export for every channel (§C8.4, D17): valid, deterministic, secrets write-only."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from channel_targets import TARGETS
from jsonschema import Draft202012Validator

from app.channels.base import NotificationChannel
from app.channels.schema_export import JSON_SCHEMA_DIALECT, export_schema, schema_etag

KEYS = sorted(TARGETS)


@pytest.fixture(params=KEYS)
def channel(request: pytest.FixtureRequest) -> NotificationChannel:
    factory: Callable[[], NotificationChannel] = TARGETS[request.param]
    return factory()


def _export(channel: NotificationChannel) -> dict[str, Any]:
    return export_schema(type(channel))


def test_the_export_is_a_valid_json_schema(channel: NotificationChannel) -> None:
    schema = _export(channel)
    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == JSON_SCHEMA_DIALECT
    assert schema["$id"] == f"/api/v1/notification-channels/{channel.key}/schema"
    assert schema["type"] == "object"
    json.dumps(schema)


def test_every_secret_field_is_write_only_with_no_default_or_example(channel: NotificationChannel) -> None:
    properties = _export(channel).get("properties", {})
    for name in channel.secret_fields:
        prop = properties[name]
        assert prop["writeOnly"] is True
        assert prop["format"] == "password"
        assert prop["x-assetflow-secret"] is True
        assert "default" not in prop
        assert "examples" not in prop


def test_only_secret_fields_are_marked_secret(channel: NotificationChannel) -> None:
    marked = {n for n, p in _export(channel).get("properties", {}).items() if p.get("x-assetflow-secret")}
    assert marked == set(channel.secret_fields)


def test_the_export_is_deterministic_and_has_a_stable_etag(channel: NotificationChannel) -> None:
    first, second = _export(channel), _export(channel)
    assert first == second
    assert schema_etag(first) == schema_etag(second)
    assert schema_etag(first).startswith('"')


def test_the_etag_changes_when_the_schema_does(channel: NotificationChannel) -> None:
    schema = _export(channel)
    changed = {**schema, "title": "something else"}
    assert schema_etag(schema) != schema_etag(changed)


def test_the_export_holds_no_translated_ui_text(channel: NotificationChannel) -> None:
    """Titles and descriptions are the model's own keys' text for developers; no locale-specific text."""
    text = json.dumps(_export(channel), ensure_ascii=False)
    assert all(ord(ch) < 128 for ch in text)  # keys and plain English only; translation is the frontend's job


def test_the_webhook_schema_describes_its_settings() -> None:
    schema = export_schema(type(TARGETS["webhook"]()))
    assert set(schema["required"]) >= {"url", "signing_secret", "events"}
    assert schema["properties"]["signing_secret"]["minLength"] == 16
    valid = {
        "url": "https://hooks.example.test/in",
        "signing_secret": "a-secret-of-sixteen+",
        "events": ["team_member.added"],
        "field_mapping": {"member": "member_id"},
    }
    validator = Draft202012Validator(schema)
    assert list(validator.iter_errors(valid)) == []
    assert any(e.path[-1] == "events" for e in validator.iter_errors({**valid, "events": []}))
    assert any(
        "signing_secret" in e.path for e in validator.iter_errors({**valid, "signing_secret": "short"})
    )


def test_the_email_schema_describes_its_settings() -> None:
    schema = export_schema(type(TARGETS["email"]()))
    assert set(schema["properties"]) == {"from_address", "from_name", "reply_to"}
    assert not schema.get("required")
    assert not schema.get("additionalProperties", True)
