# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Egress enforcement (§B6.3 rule 2, §C8.4): what an allowlisted channel client may reach."""

from __future__ import annotations

from typing import Any, ClassVar

import httpx
import pytest
from channel_targets import ORG, PUBLIC_ADDRESS
from pydantic import BaseModel

from app.channels.base import ChannelContext, DeliveryResult, NotificationChannel, RenderedMessage
from app.channels.egress import EgressClient
from app.channels.runtime import ChannelRuntime
from app.core.problems import ChannelEgressDeniedError

HOST = "hooks.example.test"


class _Settings(BaseModel):
    pass


class _CallsOut(NotificationChannel):
    """A stand-in for a webhook-style channel: one built-in host, installation hosts on top."""

    key: ClassVar[str] = "calls-out"
    config_schema: ClassVar[type[BaseModel]] = _Settings
    egress_hosts: ClassVar[tuple[str, ...]] = (HOST,)

    async def send(
        self, ctx: ChannelContext, target: str, message: RenderedMessage, idempotency_key: str
    ) -> DeliveryResult:
        raise NotImplementedError

    async def health(self, ctx: ChannelContext) -> dict[str, Any]:
        return {"healthy": True}


class _Resolver:
    """Answers each lookup from a script; the last answer repeats."""

    def __init__(self, *answers: list[str]) -> None:
        self.answers = list(answers)
        self.calls = 0

    async def __call__(self, host: str, port: int) -> list[str]:
        answer = self.answers[min(self.calls, len(self.answers) - 1)]
        self.calls += 1
        return answer


def _client(resolver: _Resolver, seen: list[httpx.Request], hosts: list[str] | None = None) -> EgressClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    return EgressClient(hosts or [HOST], resolver=resolver, transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.0.0.1", "169.254.169.254", "192.168.1.5", "172.16.0.9", "0.0.0.0", "100.64.0.1"],  # noqa: S104
)
async def test_a_name_that_resolves_to_a_private_ipv4_address_is_blocked(address: str) -> None:
    seen: list[httpx.Request] = []
    with pytest.raises(ChannelEgressDeniedError):
        await _client(_Resolver([address]), seen).request("POST", f"https://{HOST}/hook")
    assert seen == []


@pytest.mark.parametrize(
    "address", ["::1", "::ffff:127.0.0.1", "fe80::1", "fc00::1", "64:ff9b::7f00:1", "::"]
)
async def test_a_name_that_resolves_to_a_private_ipv6_address_is_blocked(address: str) -> None:
    seen: list[httpx.Request] = []
    with pytest.raises(ChannelEgressDeniedError):
        await _client(_Resolver([address]), seen).request("POST", f"https://{HOST}/hook")
    assert seen == []


async def test_one_private_address_among_public_ones_blocks_the_call() -> None:
    seen: list[httpx.Request] = []
    with pytest.raises(ChannelEgressDeniedError):
        await _client(_Resolver([PUBLIC_ADDRESS, "10.0.0.1"]), seen).request("POST", f"https://{HOST}/hook")
    assert seen == []


async def test_a_destination_that_re_resolves_to_loopback_is_blocked_on_the_next_call() -> None:
    seen: list[httpx.Request] = []
    client = _client(_Resolver([PUBLIC_ADDRESS], ["127.0.0.1"]), seen)
    assert (await client.request("POST", f"https://{HOST}/hook")).status_code == 200
    with pytest.raises(ChannelEgressDeniedError):
        await client.request("POST", f"https://{HOST}/hook")
    assert len(seen) == 1


async def test_the_request_connects_to_the_address_that_passed_the_check() -> None:
    seen: list[httpx.Request] = []
    resolver = _Resolver([PUBLIC_ADDRESS], ["10.0.0.1"])
    await _client(resolver, seen).request("POST", f"https://{HOST}/hook?x=1", json={"a": 1})
    request = seen[0]
    assert request.url.host == PUBLIC_ADDRESS
    assert request.headers["host"] == HOST
    assert request.extensions["sni_hostname"] == HOST
    assert resolver.calls == 1


async def test_a_host_outside_the_allowlist_is_blocked_before_any_lookup() -> None:
    seen: list[httpx.Request] = []
    resolver = _Resolver([PUBLIC_ADDRESS])
    with pytest.raises(ChannelEgressDeniedError):
        await _client(resolver, seen).request("POST", "https://elsewhere.example.test/hook")
    assert resolver.calls == 0
    assert seen == []


@pytest.mark.parametrize(
    "url",
    [
        "http://hooks.example.test/hook",
        "https://user:pw@hooks.example.test/hook",
        "https:///hook",
        "ftp://hooks.example.test/",
    ],
)
async def test_only_plain_https_urls_without_credentials_are_allowed(url: str) -> None:
    seen: list[httpx.Request] = []
    with pytest.raises(ChannelEgressDeniedError):
        await _client(_Resolver([PUBLIC_ADDRESS]), seen).request("POST", url)
    assert seen == []


@pytest.mark.parametrize(
    "literal", ["[::1]", "127.0.0.1", "[::ffff:127.0.0.1]", "169.254.169.254", "10.0.0.1"]
)
async def test_an_address_literal_is_blocked_even_when_it_is_allowlisted(literal: str) -> None:
    seen: list[httpx.Request] = []
    host = literal.strip("[]")
    client = _client(_Resolver([host]), seen, hosts=[host])
    with pytest.raises(ChannelEgressDeniedError):
        await client.request("POST", f"https://{literal}/hook")
    assert seen == []


async def test_a_name_that_does_not_resolve_is_blocked() -> None:
    async def failing(host: str, port: int) -> list[str]:
        raise OSError("no such host")

    client = EgressClient(
        [HOST], resolver=failing, transport=httpx.MockTransport(lambda r: httpx.Response(200))
    )
    with pytest.raises(ChannelEgressDeniedError):
        await client.request("GET", f"https://{HOST}/")


async def test_redirects_are_not_followed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://127.0.0.1/admin"})

    client = EgressClient(
        [HOST], resolver=_Resolver([PUBLIC_ADDRESS]), transport=httpx.MockTransport(handler)
    )
    assert (await client.request("GET", f"https://{HOST}/")).status_code == 302


async def test_the_runtime_gives_a_channel_its_declared_hosts_plus_the_installation_hosts(
    runtime: ChannelRuntime,
) -> None:
    ctx = await runtime.build_context(_CallsOut(), ORG, {"allowed_hosts": ["extra.example.test"]})
    assert isinstance(ctx.http, EgressClient)
    assert ctx.http._allowed == {HOST, "extra.example.test"}


async def test_a_public_ipv6_answer_is_pinned_with_the_original_host_header() -> None:
    seen: list[httpx.Request] = []
    await _client(_Resolver(["2606:2800:220:1:248:1893:25c8:1946"]), seen).request("GET", f"https://{HOST}/x")
    assert seen[0].url.host == "2606:2800:220:1:248:1893:25c8:1946"
    assert seen[0].headers["host"] == HOST


async def test_environment_proxies_are_never_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.internal:3128")
    seen: list[httpx.Request] = []
    await _client(_Resolver([PUBLIC_ADDRESS]), seen).request("GET", f"https://{HOST}/x")
    assert seen[0].url.host == PUBLIC_ADDRESS
