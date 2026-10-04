# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The `webhook` channel (§B6.3, §C6.7, §C8.4, M1.5-T5): signing, mapping, personal data, egress, retries.

The destination is a recorded HTTP exchange (`httpx.MockTransport` behind the real egress client),
so every check also exercises the HTTPS-only, public-address and no-redirect rules.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import time_machine
from channel_targets import ORG, PUBLIC_ADDRESS
from pydantic import ValidationError

from app.channels.base import ChannelContext, RenderedMessage
from app.channels.egress import EgressClient
from app.channels.webhook import WebhookChannel, WebhookSettings
from app.channels.webhook_mapping import build_payload, canonical_json, mapping_problems
from app.engines.automation.registry import EventFieldRegistry

HOST = "hooks.example.test"
URL = f"https://{HOST}/inbound?token=abc"
SECRET = "whsec-this-is-a-throwaway-test-secret"
KEY = "c" * 64
EVENT_ID = "0192f000-0000-7000-8000-0000000000c1"
NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
MAPPING = {"team.id": "team_id", "team.role": "team_role", "member": "member_id"}
SETTINGS: dict[str, Any] = {
    "url": URL,
    "events": ["team_member.added"],
    "field_mapping": MAPPING,
    "include_personal_data": False,
}
FIELDS = {"payload": {"member": "m-1", "team": {"id": "t-1", "role": "lead"}}, "occurred_at": NOW.isoformat()}


async def _public(name: str, port: int) -> list[str]:
    return [PUBLIC_ADDRESS]


def _ctx(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    settings: dict[str, Any] | None = None,
    resolver: Any = _public,
) -> ChannelContext:
    return ChannelContext(
        organization_id=ORG,
        installation={"settings": settings or SETTINGS},
        credentials={"signing_secret": SECRET},  # type: ignore[arg-type]
        http=EgressClient([HOST], resolver=resolver, transport=httpx.MockTransport(handler)),
    )


def _message(fields: dict[str, Any] | None = None) -> RenderedMessage:
    return RenderedMessage(
        subject="x",
        body="",
        data={
            "event_type": "team_member.added",
            "event_id": EVENT_ID,
            "template_key": "team-member-added",
            "fields": FIELDS if fields is None else fields,
        },
    )


def _ok(seen: list[httpx.Request], status: int = 200) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status)

    return handler


def verify(
    secret: str, headers: httpx.Headers, body: bytes, *, now: datetime = NOW, window: int = 300
) -> bool:
    """What a receiver does: check the timestamp window, then the signature in constant time."""
    timestamp = headers["x-assetflow-timestamp"]
    if abs(int(now.timestamp()) - int(timestamp)) > window:
        return False
    expected = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(headers["x-assetflow-signature"], f"sha256={expected}")


@time_machine.travel(NOW, tick=False)
async def test_a_signed_request_with_the_mapped_fields_is_delivered() -> None:
    seen: list[httpx.Request] = []
    result = await WebhookChannel().send(_ctx(_ok(seen)), "member-1", _message(), KEY)

    assert result.delivered
    request = seen[0]
    assert request.method == "POST"
    assert request.headers["content-type"] == "application/json"
    assert request.headers["host"] == HOST
    assert request.url.host == PUBLIC_ADDRESS  # connected to the checked address
    assert request.url.query == b"token=abc"
    body = request.content
    assert verify(SECRET, request.headers, body)
    assert json.loads(body) == {
        "event_type": "team_member.added",
        "event_id": EVENT_ID,
        "occurred_at": NOW.isoformat(),
        "organization_id": ORG,
        "member": "m-1",
        "team": {"id": "t-1", "role": "lead"},
    }
    assert body == canonical_json(json.loads(body))  # the signed bytes are the canonical serialization


@time_machine.travel(NOW, tick=False)
async def test_the_delivery_id_is_the_idempotency_key_and_the_timestamp_is_unix_seconds() -> None:
    seen: list[httpx.Request] = []
    await WebhookChannel().send(_ctx(_ok(seen)), "member-1", _message(), KEY)
    assert seen[0].headers["x-assetflow-delivery-id"] == KEY
    assert seen[0].headers["x-assetflow-timestamp"] == str(int(NOW.timestamp()))


@time_machine.travel(NOW, tick=False)
async def test_a_tampered_body_or_wrong_secret_or_stale_timestamp_fails_verification() -> None:
    seen: list[httpx.Request] = []
    await WebhookChannel().send(_ctx(_ok(seen)), "member-1", _message(), KEY)
    headers, body = seen[0].headers, seen[0].content
    assert verify(SECRET, headers, body)
    assert not verify(SECRET, headers, body + b" ")
    assert not verify("a-different-secret-value", headers, body)
    assert not verify(
        SECRET, headers, body, now=datetime(2026, 3, 1, 12, 5, 1, tzinfo=UTC)
    )  # older than 5 minutes
    assert verify(SECRET, headers, body, now=datetime(2026, 3, 1, 12, 4, 59, tzinfo=UTC))


async def test_only_mapped_fields_are_sent() -> None:
    seen: list[httpx.Request] = []
    fields = {"payload": {"member": "m-1"}, "occurred_at": None}
    await WebhookChannel().send(_ctx(_ok(seen)), "member-1", _message(fields), KEY)
    body = json.loads(seen[0].content)
    assert set(body) == {"event_type", "event_id", "occurred_at", "organization_id", "member"}
    assert "team" not in body


# --------------------------------------------------------------------------------- mapping


def test_mapped_fields_nest_by_target_path_and_unmapped_ones_are_absent() -> None:
    data = {"team_id": "t-1", "team_role": "lead", "member_id": "m-1", "secret_note": "never sent"}
    payload = build_payload(MAPPING, data, personal_fields=frozenset(), allow_personal=False)
    assert payload == {"member": "m-1", "team": {"id": "t-1", "role": "lead"}}
    assert "secret_note" not in json.dumps(payload)


def test_a_mapped_field_the_event_did_not_carry_is_left_out() -> None:
    assert build_payload(
        {"a": "x", "b": "y"}, {"x": 1}, personal_fields=frozenset(), allow_personal=True
    ) == {"a": 1}


@pytest.mark.parametrize(
    ("setting", "allow", "present"), [(False, True, False), (True, False, False), (True, True, True)]
)
def test_personal_fields_need_both_switches(setting: bool, allow: bool, present: bool) -> None:
    registry = EventFieldRegistry()
    registry.register_event("person.event", {"id", "display_name"}, personal_fields={"display_name"})
    settings = {
        "events": ["person.event"],
        "field_mapping": {"who": "display_name", "id": "id"},
        "include_personal_data": setting,
    }
    data = WebhookChannel(event_registry=registry).build_message_data(
        settings, "person.event", {"id": "1", "display_name": "Ada"}, NOW, allow_personal=allow
    )
    assert data is not None
    assert ("who" in data["payload"]) is present
    assert data["payload"]["id"] == "1"


def test_unwanted_events_are_not_queued_and_the_destination_host_is_derived() -> None:
    channel = WebhookChannel()
    assert channel.accepts_event(SETTINGS, "team_member.added")
    assert not channel.accepts_event(SETTINGS, "team.created")
    assert WebhookChannel.allowed_hosts_for(SETTINGS) == [HOST]
    assert WebhookChannel.allowed_hosts_for({}) == []


# ----------------------------------------------------------------------------- settings


def _settings(**changes: Any) -> dict[str, Any]:
    return {**SETTINGS, "signing_secret": SECRET, **changes}


def test_valid_settings_are_accepted() -> None:
    parsed = WebhookSettings.model_validate(_settings())
    assert parsed.signing_secret.get_secret_value() == SECRET
    assert SECRET not in repr(parsed)


@pytest.mark.parametrize(
    "changes",
    [
        {"url": "http://hooks.example.test/in"},
        {"url": "https://user:pw@hooks.example.test/in"},
        {"url": "https:///in"},
        {"url": "ftp://hooks.example.test/in"},
        {"url": "https://hooks.example.test/in#frag"},
        {"signing_secret": "short"},
        {"events": []},
        {"events": ["no.such.event"]},
        {"field_mapping": {"x": "not_a_field"}},
        {"field_mapping": {"event_id": "team_id"}},
        {"field_mapping": {"occurred_at.sub": "team_id"}},
        {"field_mapping": {"a": "team_id", "a.b": "team_role"}},
        {"field_mapping": {"bad path": "team_id"}},
        {"field_mapping": {"x": "team_role"}, "events": ["team_member.added", "team.archived"]},
        {"unknown": 1},
    ],
)
def test_invalid_settings_are_refused_at_save_time(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        WebhookSettings.model_validate(_settings(**changes))


def test_mapping_problems_name_the_path() -> None:
    registry = EventFieldRegistry()
    registry.register_event("e.one", {"a"})
    problems = mapping_problems({"x": "missing", "event_type": "a"}, ["e.one"], registry)
    assert [path for path, _ in problems] == ["field_mapping.event_type", "field_mapping.x"]


# ------------------------------------------------------------------------------- egress


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "::ffff:127.0.0.1"])
async def test_a_destination_on_a_private_address_is_blocked_and_not_retried(address: str) -> None:
    seen: list[httpx.Request] = []

    async def resolver(name: str, port: int) -> list[str]:
        return [address]

    result = await WebhookChannel().send(_ctx(_ok(seen), resolver=resolver), "m", _message(), KEY)
    assert (result.delivered, result.error_code, result.retryable) == (False, "channel.egress_denied", False)
    assert seen == []


async def test_a_destination_that_re_resolves_to_loopback_is_blocked_on_the_retry() -> None:
    answers = iter([[PUBLIC_ADDRESS], ["127.0.0.1"]])

    async def resolver(name: str, port: int) -> list[str]:
        return next(answers)

    seen: list[httpx.Request] = []
    ctx = _ctx(_ok(seen), resolver=resolver)
    channel = WebhookChannel()
    assert (await channel.send(ctx, "m", _message(), KEY)).delivered
    second = await channel.send(ctx, "m", _message(), KEY)
    assert (second.error_code, second.retryable) == ("channel.egress_denied", False)
    assert len(seen) == 1


async def test_a_plain_http_url_in_the_stored_settings_is_refused_at_send_time_too() -> None:
    seen: list[httpx.Request] = []
    settings = {**SETTINGS, "url": f"http://{HOST}/in"}
    result = await WebhookChannel().send(_ctx(_ok(seen), settings=settings), "m", _message(), KEY)
    assert result.error_code == "channel.egress_denied"
    assert seen == []


async def test_a_host_that_is_not_the_allowlisted_one_is_blocked() -> None:
    seen: list[httpx.Request] = []
    settings = {**SETTINGS, "url": "https://elsewhere.example.test/in"}
    result = await WebhookChannel().send(_ctx(_ok(seen), settings=settings), "m", _message(), KEY)
    assert result.error_code == "channel.egress_denied"
    assert seen == []


async def test_a_redirect_is_not_followed_and_is_not_retried() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(302, headers={"location": "https://127.0.0.1/admin"})

    result = await WebhookChannel().send(_ctx(handler), "m", _message(), KEY)
    assert (result.delivered, result.error_code, result.retryable) == (False, "http_302", False)
    assert len(seen) == 1


# ------------------------------------------------------------------------------- retries


@pytest.mark.parametrize("status", [200, 201, 202, 204])
async def test_2xx_is_delivered(status: int) -> None:
    assert (await WebhookChannel().send(_ctx(_ok([], status)), "m", _message(), KEY)).delivered


@pytest.mark.parametrize("status", [500, 502, 503, 504])
async def test_5xx_is_retried(status: int) -> None:
    result = await WebhookChannel().send(_ctx(_ok([], status)), "m", _message(), KEY)
    assert (result.delivered, result.error_code, result.retryable) == (False, f"http_{status}", True)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 410, 422, 429])
async def test_every_4xx_is_not_retried(status: int) -> None:
    result = await WebhookChannel().send(_ctx(_ok([], status)), "m", _message(), KEY)
    assert (result.delivered, result.error_code, result.retryable) == (False, f"http_{status}", False)


@pytest.mark.parametrize(
    ("exc", "code"),
    [(httpx.ReadTimeout("slow"), "timeout"), (httpx.ConnectError("refused"), "connection_error")],
)
async def test_timeouts_and_connection_errors_are_retried(exc: Exception, code: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    result = await WebhookChannel().send(_ctx(handler), "m", _message(), KEY)
    assert (result.delivered, result.error_code, result.retryable) == (False, code, True)


async def test_the_same_key_sends_the_same_delivery_id_each_time() -> None:
    seen: list[httpx.Request] = []
    ctx = _ctx(_ok(seen))
    for _ in range(2):
        await WebhookChannel().send(ctx, "m", _message(), KEY)
    assert {r.headers["x-assetflow-delivery-id"] for r in seen} == {KEY}


async def test_missing_configuration_fails_without_retrying() -> None:
    bare = ChannelContext(organization_id=ORG, installation={"settings": SETTINGS}, http=None)
    result = await WebhookChannel().send(bare, "m", _message(), KEY)
    assert (result.error_code, result.retryable) == ("webhook.not_configured", False)


# --------------------------------------------------------------------------- secrecy, health


async def test_the_secret_never_reaches_logs_results_or_the_repr(caplog: pytest.LogCaptureFixture) -> None:
    ctx = _ctx(_ok([], 500))
    with caplog.at_level(logging.DEBUG):
        result = await WebhookChannel().send(ctx, "m", _message(), KEY)
    assert SECRET not in caplog.text
    assert SECRET not in repr(result)
    assert SECRET not in repr(ctx)


async def test_health_sends_nothing_and_reports_public_or_degraded() -> None:
    seen: list[httpx.Request] = []
    assert await WebhookChannel().health(_ctx(_ok(seen))) == {"healthy": True, "status": "healthy"}
    assert seen == []

    async def private(name: str, port: int) -> list[str]:
        return ["10.0.0.5"]

    assert await WebhookChannel().health(_ctx(_ok(seen), resolver=private)) == {
        "healthy": False,
        "status": "degraded",
    }
    assert seen == []
    unconfigured = ChannelContext(organization_id=ORG, installation={})
    assert (await WebhookChannel().health(unconfigured))["status"] == "not_configured"
