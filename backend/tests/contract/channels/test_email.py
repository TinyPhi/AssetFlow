# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The `email` channel against a local SMTP server with real TLS (§B6.3, §C6.7, §C8.4, M1.5-T4).

Covers delivery (STARTTLS, implicit TLS, plain for a local catcher), what the message contains,
retry classification of SMTP replies, idempotency through `Message-ID`, the address check, the
personal-data rules, and that no recipient address leaks into a result or a log.
"""

from __future__ import annotations

import email
import logging
from email import policy
from email.message import EmailMessage
from typing import Any

import pytest
from channel_targets import ORG
from fake_smtp import SERVER_NAME, FakeSmtp, Script, run_server

from app.channels.base import ChannelContext, DeliveryResult, Recipient, RenderedMessage
from app.channels.egress import EgressClient
from app.channels.email import EmailChannel
from app.core.config import EmailChannelConfig

MEMBER = "0192f000-0000-7000-8000-0000000000b1"
ADDRESS = "ada.lovelace@members.example.test"
KEY = "a" * 64
PASSWORD = "relay-password-for-this-test"
DEVANAGARI = "नमस्ते टीम, आपको जोड़ा गया है"


ADA = Recipient(address=ADDRESS, display_name="Ada Lovelace")


class _Recipients:
    def __init__(self, recipient: Recipient | None) -> None:
        self.recipient, self.asked = recipient, []

    async def resolve(self, member_id: str) -> Recipient | None:
        self.asked.append(member_id)
        return self.recipient


def _message(subject: str = "You were added to a team", **overrides: Any) -> RenderedMessage:
    values: dict[str, Any] = {
        "subject": subject,
        "body": f"<p>{DEVANAGARI}</p>",
        "text": DEVANAGARI,
        "data": {"event_type": "team_member.added"},
    }
    values.update(overrides)
    return RenderedMessage(**values)


def _ctx(
    server: FakeSmtp,
    *,
    security: str = "starttls",
    settings: dict[str, Any] | None = None,
    recipient: Recipient | None = ADA,
    resolver_ip: str = "127.0.0.1",
    allow_private: bool = True,
    host: str = SERVER_NAME,
    allowed: tuple[str, ...] = (SERVER_NAME,),
    password: str | None = None,
) -> ChannelContext:
    platform = EmailChannelConfig(
        enabled=True,
        host=host,
        port=server.port,
        security=security,  # type: ignore[arg-type]
        username="relay-user" if password else None,
        default_from="noreply@platform.example.test",
        timeout_seconds=2.0,
        allow_private_addresses=allow_private,
    ).model_dump()

    async def resolve(name: str, port: int) -> list[str]:
        return [resolver_ip]

    return ChannelContext(
        organization_id=ORG,
        installation={"settings": settings or {}},
        credentials={"password": password} if password else {},  # type: ignore[arg-type]
        http=EgressClient(allowed, resolver=resolve, allow_private_addresses=allow_private),
        platform=platform,
        recipients=_Recipients(recipient),
    )


def _channel(server: FakeSmtp, *, trusted: bool = True) -> EmailChannel:
    context = (
        server.certificates.trusting_client_context if trusted else server.certificates.default_client_context
    )
    return EmailChannel(tls_context=context)


def _parsed(server: FakeSmtp, index: int = 0) -> EmailMessage:
    parsed = email.message_from_bytes(server.received.messages[index], policy=policy.default)
    assert isinstance(parsed, EmailMessage)
    return parsed


async def _send(
    server: FakeSmtp, ctx: ChannelContext, *, trusted: bool = True, key: str = KEY
) -> DeliveryResult:
    return await _channel(server, trusted=trusted).send(ctx, MEMBER, _message(), key)


async def test_starttls_delivers_a_multipart_message_with_the_right_headers() -> None:
    async with run_server() as server:
        ctx = _ctx(server, settings={"from_address": "alerts@org.example.test", "from_name": "Org Alerts"})
        result = await _send(server, ctx)

        assert result.delivered
        assert server.received.tls_sessions == 1  # upgraded before any message was sent
        assert server.received.senders == ["alerts@org.example.test"]
        assert server.received.recipients == [ADDRESS]
        message = _parsed(server)
        assert message["From"] == "Org Alerts <alerts@org.example.test>"
        assert message["To"] == "Ada Lovelace <ada.lovelace@members.example.test>"
        assert message["Subject"] == "You were added to a team"
        assert message["Message-ID"] == f"<{KEY}@org.example.test>"
        assert message.get_content_type() == "multipart/alternative"
        text, html = message.get_body(("plain",)), message.get_body(("html",))
        assert text is not None and html is not None
        assert text.get_content().strip() == DEVANAGARI
        assert DEVANAGARI in html.get_content()


async def test_the_platform_sender_is_used_when_the_organization_sets_none() -> None:
    async with run_server() as server:
        await _send(server, _ctx(server))
        assert server.received.senders == ["noreply@platform.example.test"]
        assert _parsed(server)["Message-ID"] == f"<{KEY}@platform.example.test>"


async def test_the_reply_to_is_set_from_the_organization_settings() -> None:
    async with run_server() as server:
        await _send(server, _ctx(server, settings={"reply_to": "help@org.example.test"}))
        assert _parsed(server)["Reply-To"] == "help@org.example.test"


async def test_implicit_tls_delivers() -> None:
    async with run_server(implicit_tls=True) as server:
        result = await _send(server, _ctx(server, security="tls"))
        assert result.delivered
        assert server.received.tls_sessions == 1


async def test_plain_smtp_delivers_for_a_local_catcher() -> None:
    async with run_server(tls=False) as server:
        result = await _send(server, _ctx(server, security="none"))
        assert result.delivered
        assert server.received.tls_sessions == 0


async def test_an_untrusted_certificate_is_refused_and_not_retried() -> None:
    async with run_server() as server:
        result = await _send(server, _ctx(server), trusted=False)
        assert (result.delivered, result.error_code, result.retryable) == (False, "tls_certificate", False)
        assert server.received.messages == []


async def test_starttls_is_required_when_the_server_does_not_offer_it() -> None:
    async with run_server(script=Script(advertise_starttls=False)) as server:
        result = await _send(server, _ctx(server))
        assert not result.delivered
        assert server.received.messages == []  # nothing was sent in the clear


async def test_the_relay_password_is_sent_only_after_tls() -> None:
    async with run_server(script=Script(require_auth=True)) as server:
        result = await _send(server, _ctx(server, password=PASSWORD))
        assert result.delivered
        assert server.received.auth == [("relay-user", PASSWORD)]
        assert server.received.tls_sessions == 1


@pytest.mark.parametrize(
    ("replies", "code", "retryable"),
    [
        ({"RCPT": "450 mailbox busy, try later"}, "smtp_450", True),
        ({"DATA_END": "451 local error in processing"}, "smtp_451", True),
        ({"MAIL": "421 service shutting down"}, "smtp_421", True),
        ({"RCPT": "550 no such user"}, "smtp_550", False),
        ({"RCPT": "553 mailbox name not allowed"}, "smtp_553", False),
        ({"DATA_END": "554 transaction failed"}, "smtp_554", False),
    ],
)
async def test_smtp_reply_classes_map_to_retryable_or_not(
    replies: dict[str, str], code: str, retryable: bool
) -> None:
    async with run_server(tls=False, script=Script(replies=replies)) as server:
        result = await _send(server, _ctx(server, security="none"))
        assert (result.delivered, result.error_code, result.retryable) == (False, code, retryable)
        assert ADDRESS not in repr(result)


async def test_a_lost_connection_is_retryable() -> None:
    async with run_server(tls=False, script=Script(drop_after="EHLO")) as server:
        result = await _send(server, _ctx(server, security="none"))
        assert (result.delivered, result.error_code, result.retryable) == (False, "connection_error", True)


async def test_a_server_that_never_greets_times_out_and_is_retryable() -> None:
    async with run_server(tls=False, script=Script(silent_greeting=True)) as server:
        ctx = _ctx(server, security="none")
        ctx.platform["timeout_seconds"] = 0.3
        result = await _send(server, ctx)
        assert (result.delivered, result.error_code, result.retryable) == (False, "timeout", True)


async def test_the_same_key_gives_the_same_message_id() -> None:
    async with run_server(tls=False) as server:
        for _ in range(2):
            await _send(server, _ctx(server, security="none"))
        first, second = _parsed(server, 0), _parsed(server, 1)
        assert first["Message-ID"] == second["Message-ID"] == f"<{KEY}@platform.example.test>"
        other = await _send(server, _ctx(server, security="none"), key="b" * 64)
        assert other.delivered
        assert _parsed(server, 2)["Message-ID"] != first["Message-ID"]


async def test_a_member_who_cannot_be_reached_is_skipped_not_failed() -> None:
    async with run_server(tls=False) as server:
        result = await _send(server, _ctx(server, security="none", recipient=None))
        assert (result.delivered, result.skipped, result.error_code) == (False, True, "recipient.unavailable")
        assert server.received.connections == 0


async def test_a_private_address_is_refused_unless_the_platform_allows_it() -> None:
    async with run_server(tls=False) as server:
        result = await _send(server, _ctx(server, security="none", allow_private=False))
        assert (result.delivered, result.error_code, result.retryable) == (
            False,
            "channel.egress_denied",
            False,
        )
        assert server.received.connections == 0


async def test_a_host_that_is_not_on_the_allowlist_is_refused() -> None:
    async with run_server(tls=False) as server:
        ctx = _ctx(server, security="none", allowed=("another.example.test",))
        result = await _send(server, ctx)
        assert result.error_code == "channel.egress_denied"
        assert server.received.connections == 0


async def test_the_connection_goes_to_the_checked_address_not_a_second_lookup() -> None:
    """The name only resolves to loopback in the egress check; a client that looked it up again would fail."""
    async with run_server(tls=False) as server:
        result = await _send(
            server,
            _ctx(server, security="none", host="no-such-host.invalid", allowed=("no-such-host.invalid",)),
        )
        assert result.delivered
        assert server.received.connections == 1


async def test_header_injection_through_names_and_subject_is_neutralized() -> None:
    async with run_server(tls=False) as server:
        ctx = _ctx(
            server,
            security="none",
            recipient=Recipient(address=ADDRESS, display_name="Ada\r\nBcc: evil@example.test"),
        )
        result = await _channel(server).send(
            ctx, MEMBER, _message(subject="Hello\r\nBcc: evil@example.test"), KEY
        )
        assert result.delivered
        message = _parsed(server)
        assert message["Bcc"] is None
        assert "\n" not in str(message["Subject"])
        assert server.received.recipients == [ADDRESS]


@pytest.mark.parametrize(
    "settings",
    [
        {"from_address": "not-an-address"},
        {"from_address": "a@b.example.test\r\nBcc: x@y.example.test"},
        {"reply_to": "x y@z.test"},
        {"from_name": "a\x00b"},
    ],
)
async def test_invalid_organization_settings_are_not_sent(settings: dict[str, Any]) -> None:
    async with run_server(tls=False) as server:
        result = await _send(server, _ctx(server, security="none", settings=settings))
        assert (result.delivered, result.retryable) == (False, False)
        assert server.received.connections == 0


async def test_an_unconfigured_channel_fails_without_retrying() -> None:
    async with run_server(tls=False) as server:
        ctx = _ctx(server, security="none")
        bare = ChannelContext(organization_id=ORG, installation={}, recipients=ctx.recipients)
        result = await _channel(server).send(bare, MEMBER, _message(), KEY)
        assert (result.error_code, result.retryable) == ("email.not_configured", False)


async def test_the_address_and_password_never_reach_the_logs(caplog: pytest.LogCaptureFixture) -> None:
    async with run_server(script=Script(require_auth=True, replies={"RCPT": "550 no such user"})) as server:
        with caplog.at_level(logging.DEBUG):
            await _send(server, _ctx(server, password=PASSWORD))
    assert ADDRESS not in caplog.text
    assert PASSWORD not in caplog.text
    assert "Ada Lovelace" not in caplog.text


async def test_the_context_repr_shows_no_address_or_password() -> None:
    async with run_server(tls=False) as server:
        ctx = _ctx(server, security="none", password=PASSWORD)
        assert PASSWORD not in repr(ctx)
        assert ADDRESS not in repr(ctx)
        assert ADDRESS not in repr(Recipient(address=ADDRESS, display_name="Ada"))


async def test_health_reports_healthy_with_a_noop() -> None:
    async with run_server() as server:
        health = await _channel(server).health(_ctx(server))
        assert health == {"healthy": True, "status": "healthy"}


async def test_health_degraded_never_leaks_the_server_text() -> None:
    async with run_server(
        tls=False, script=Script(replies={"NOOP": "421 secret-banner-text go away"})
    ) as server:
        health = await _channel(server).health(_ctx(server, security="none"))
        assert health == {"healthy": False, "status": "degraded"}
    assert (await EmailChannel().health(ChannelContext(organization_id=ORG, installation={})))[
        "healthy"
    ] is False
