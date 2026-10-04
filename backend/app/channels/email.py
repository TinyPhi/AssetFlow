# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The `email` channel: HTML and text mail over SMTP (§B6.3 `email` row, M1.5-T4, §C5.8).

The SMTP relay and its credentials belong to the installation (platform config, password by
`secret://` reference, read only by the runtime); each organization sets only its own sender. The
recipient's address is read from the member record at send time and never leaves this function: not
in a log, a trace, a metric tag or `notification_deliveries` (whose `target` stays the member id).

The connection goes to the address the egress check approved (a pre-connected socket), with the
relay's name kept for certificate verification, so a DNS answer that changes in between cannot
redirect the mail. `starttls` and `tls` verify the certificate; `none` exists for a local mail
catcher and is refused in production by the platform config.

SMTP reply classes run the other way round from HTTP's, so they are mapped onto the runtime's
rule here: a 4yz reply, a timeout or a lost connection is retryable; a 5yz reply is not.
"""

from __future__ import annotations

import asyncio
import re
import socket
import ssl
import time
from dataclasses import replace
from email.message import EmailMessage
from email.utils import formataddr, formatdate
from typing import Any, ClassVar

import aiosmtplib
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.channels.base import ChannelContext, DeliveryResult, NotificationChannel, Recipient, RenderedMessage
from app.channels.retry import failure_from_exception
from app.core.config import EmailChannelConfig

__all__ = ["EmailChannel", "EmailSettings"]

_ADDRESS = re.compile(r"^[^@\s<>,;\"]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _check_address(value: str | None) -> str | None:
    if value is not None and _ADDRESS.match(value) is None:
        raise ValueError("must be a plain email address")
    return value


class EmailSettings(BaseModel):
    """Per-organization settings of the `email` channel: the sender only; no secrets (§B6.3)."""

    model_config = ConfigDict(extra="forbid")

    from_address: str | None = Field(
        default=None, description="Sender address; the platform default when unset"
    )
    from_name: str | None = Field(default=None, max_length=120, description="Sender display name")
    reply_to: str | None = Field(default=None, description="Reply-To address")

    @field_validator("from_address", "reply_to")
    @classmethod
    def _address(cls, value: str | None) -> str | None:
        return _check_address(value)

    @field_validator("from_name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        if value is not None and _CONTROL.search(value):
            raise ValueError("must not contain control characters")
        return value


def _clean_name(value: str) -> str:
    return _CONTROL.sub(" ", value).strip()


def _smtp_reply(code: int, latency_ms: int) -> DeliveryResult:
    return DeliveryResult(False, f"smtp_{code}", latency_ms, retryable=400 <= code < 500)


def _classify(exc: BaseException, latency_ms: int) -> DeliveryResult:  # noqa: PLR0911 - one return per failure class
    """Map an SMTP-side failure onto the runtime's retryable / not-retryable result."""
    if isinstance(exc, aiosmtplib.SMTPRecipientsRefused) and exc.recipients:
        return _smtp_reply(int(exc.recipients[0].code), latency_ms)
    if isinstance(exc, aiosmtplib.SMTPResponseException):
        return _smtp_reply(int(exc.code), latency_ms)
    if isinstance(exc, ssl.SSLCertVerificationError):  # also a ValueError: check it first
        return DeliveryResult(False, "tls_certificate", latency_ms, retryable=False)
    if isinstance(exc, ValueError | TypeError):  # the message could not be built (bad header value)
        return DeliveryResult(False, "email.invalid_message", latency_ms, retryable=False)
    if isinstance(exc, aiosmtplib.SMTPTimeoutError):
        return DeliveryResult(False, "timeout", latency_ms, retryable=True)
    if isinstance(exc, aiosmtplib.SMTPException | ConnectionError | ssl.SSLError):
        return DeliveryResult(False, "connection_error", latency_ms, retryable=True)
    return failure_from_exception(exc, latency_ms)


async def _open_socket(addresses: list[str], port: int, limit: float) -> socket.socket:
    """Connect to the first of the checked `addresses` that answers; the SMTP client gets the socket.

    Only addresses that passed the egress check are tried, so a name that has both an IPv6 and an
    IPv4 address still connects when one family is unreachable.
    """
    loop = asyncio.get_running_loop()
    failure: BaseException = OSError("no address to connect to")
    for address in addresses:
        sock = socket.socket(socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM)
        sock.setblocking(False)
        try:
            async with asyncio.timeout(limit):
                await loop.sock_connect(sock, (address, port))
        except (OSError, TimeoutError) as exc:
            sock.close()
            failure = exc
            continue
        return sock
    raise failure


class EmailChannel(NotificationChannel):
    """Sends one HTML + text message through the installation's SMTP relay."""

    key: ClassVar[str] = "email"
    display_name: ClassVar[str] = "Email"
    config_schema: ClassVar[type[BaseModel]] = EmailSettings
    secret_fields: ClassVar[tuple[str, ...]] = ()
    platform_secret_fields: ClassVar[tuple[str, ...]] = ("password",)

    def __init__(self, *, tls_context: ssl.SSLContext | None = None) -> None:
        self._tls_context = tls_context  # tests trust their own CA; None verifies against the system store

    def egress_allowlist(self, platform: dict[str, Any]) -> tuple[str, ...]:
        host = platform.get("host")
        return (str(host),) if host else ()

    # ------------------------------------------------------------------------------------ send

    def _build(
        self,
        cfg: EmailChannelConfig,
        settings: EmailSettings,
        recipient: Recipient,
        message: RenderedMessage,
        key: str,
    ) -> tuple[EmailMessage, str]:
        sender = settings.from_address or cfg.default_from
        msg = EmailMessage()
        msg["From"] = formataddr((settings.from_name or "", sender), charset="utf-8")
        msg["To"] = formataddr((_clean_name(recipient.display_name), recipient.address), charset="utf-8")
        msg["Subject"] = " ".join(message.subject.split())
        msg["Date"] = formatdate(localtime=False)
        msg["Message-ID"] = f"<{key}@{sender.rsplit('@', 1)[-1]}>"
        if settings.reply_to:
            msg["Reply-To"] = settings.reply_to
        msg.set_content(message.text or message.subject)
        if message.body:
            msg.add_alternative(message.body, subtype="html")
        return msg, sender

    async def _transmit(
        self,
        cfg: EmailChannelConfig,
        addresses: list[str],
        password: str | None,
        msg: EmailMessage,
        sender: str,
    ) -> None:
        sock = await _open_socket(addresses, cfg.port, cfg.timeout_seconds)
        smtp = aiosmtplib.SMTP(
            hostname=cfg.host,
            sock=sock,
            use_tls=cfg.security == "tls",
            start_tls=cfg.security == "starttls",
            tls_context=self._tls_context,
            username=cfg.username if password else None,
            password=password,
            local_hostname=sender.rsplit("@", 1)[-1],
            timeout=cfg.timeout_seconds,
        )
        async with smtp:
            await smtp.send_message(msg, sender=sender)

    @staticmethod
    def _prepare(ctx: ChannelContext) -> tuple[EmailChannelConfig, EmailSettings] | None:
        """The platform and installation settings, or None when email is not usable here."""
        try:
            cfg = EmailChannelConfig.model_validate(ctx.platform)
            settings = EmailSettings.model_validate(ctx.installation.get("settings") or {})
        except ValueError:
            return None
        if ctx.recipients is None or ctx.http is None or not cfg.enabled:
            return None
        return cfg, settings

    async def send(
        self, ctx: ChannelContext, target: str, message: RenderedMessage, idempotency_key: str
    ) -> DeliveryResult:
        """Send `message` to the member `target`; the idempotency key is the `Message-ID`."""
        started = time.monotonic()
        result = await self._send(ctx, target, message, idempotency_key)
        return replace(result, latency_ms=int((time.monotonic() - started) * 1000))

    async def _send(
        self, ctx: ChannelContext, target: str, message: RenderedMessage, idempotency_key: str
    ) -> DeliveryResult:
        prepared = self._prepare(ctx)
        if prepared is None or ctx.recipients is None or ctx.http is None:
            return DeliveryResult(False, "email.not_configured", retryable=False)
        cfg, settings = prepared
        recipient = await ctx.recipients.resolve(target)
        if recipient is None:
            return DeliveryResult(False, "recipient.unavailable", retryable=False, skipped=True)
        try:
            msg, sender = self._build(cfg, settings, recipient, message, idempotency_key)
            addresses = await ctx.http.resolve_all_checked(cfg.host, cfg.port)
            await self._transmit(cfg, addresses, ctx.credentials.get("password"), msg, sender)
        except Exception as exc:  # noqa: BLE001 - classified, never re-raised, never logged with its text
            return _classify(exc, 0)
        return DeliveryResult(delivered=True)

    # ---------------------------------------------------------------------------------- health

    async def health(self, ctx: ChannelContext) -> dict[str, Any]:
        """Connect and `NOOP`; reports only healthy / degraded, never the server's banner."""
        try:
            cfg = EmailChannelConfig.model_validate(ctx.platform)
            if ctx.http is None or not cfg.enabled:
                return {"healthy": False, "status": "not_configured"}
            addresses = await ctx.http.resolve_all_checked(cfg.host, cfg.port)
            sock = await _open_socket(addresses, cfg.port, cfg.timeout_seconds)
            smtp = aiosmtplib.SMTP(
                hostname=cfg.host,
                sock=sock,
                use_tls=cfg.security == "tls",
                start_tls=cfg.security == "starttls",
                tls_context=self._tls_context,
                timeout=cfg.timeout_seconds,
            )
            async with smtp:
                await smtp.noop()
        except Exception:  # noqa: BLE001 - any failure is "degraded"; the reason stays out of the report
            return {"healthy": False, "status": "degraded"}
        return {"healthy": True, "status": "healthy"}
