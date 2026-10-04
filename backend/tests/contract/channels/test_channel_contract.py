# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Channel contract suite (§C8.4): the checks every notification channel passes.

This part owns schema export, write-only secret fields, egress enforcement and health. Retries and
idempotency (P6-06b) and personal-data filtering (P6-04, P6-05) add their checks beside these.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest
from channel_targets import ORG, TARGETS
from pydantic import BaseModel

from app.channels.base import ChannelContext, NotificationChannel
from app.channels.egress import EgressClient
from app.channels.runtime import ChannelRuntime

KEYS = sorted(TARGETS)


@pytest.fixture(params=KEYS)
def channel(request: pytest.FixtureRequest) -> NotificationChannel:
    factory: Callable[[], NotificationChannel] = TARGETS[request.param]
    return factory()


def test_declares_its_identity(channel: NotificationChannel) -> None:
    assert channel.key
    assert channel.INTERFACE_VERSION == "1.0"
    assert issubclass(channel.config_schema, BaseModel)


def test_exports_a_json_schema(channel: NotificationChannel) -> None:
    schema = channel.config_schema.model_json_schema()
    assert schema["type"] == "object"
    json.dumps(schema)


def test_secret_fields_are_write_only_in_the_exported_schema(channel: NotificationChannel) -> None:
    schema = channel.config_schema.model_json_schema()
    properties = schema.get("properties", {})
    for name in channel.secret_fields:
        assert name in properties, f"secret field {name!r} is not in the settings schema"
        assert properties[name].get("writeOnly") is True, f"secret field {name!r} must be writeOnly"
        assert "default" not in properties[name], f"secret field {name!r} must not carry a default value"


async def test_context_has_a_client_only_when_the_channel_calls_out(
    channel: NotificationChannel, runtime: ChannelRuntime
) -> None:
    ctx = await runtime.build_context(channel, ORG, {"allowed_hosts": []})
    if channel.egress_hosts:
        assert isinstance(ctx.http, EgressClient)
    else:
        assert ctx.http is None
    assert dict(ctx.credentials) == {}


async def test_health_reports_without_secrets(channel: NotificationChannel, runtime: ChannelRuntime) -> None:
    ctx: ChannelContext = await runtime.build_context(channel, ORG, {"allowed_hosts": []})
    health = await channel.health(ctx)
    assert isinstance(health["healthy"], bool)
    assert "password" not in json.dumps(health).lower()
