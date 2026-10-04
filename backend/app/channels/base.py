# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The `NotificationChannel` interface every channel implements (§B6.3, §C5.8 security-sensitive).

Every channel declares its key, its per-organization settings schema, which of those settings are
secrets, and which hosts it may ever call (§B6.3 "Channel connector interface"). The runtime builds
`ChannelContext` for one call only; credentials come from the runtime alone and are never logged, and
the HTTP client enforces the egress allowlist on every call.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, ClassVar, Protocol

from pydantic import BaseModel

__all__ = [
    "ChannelContext",
    "DeliveryResult",
    "NotificationChannel",
    "Recipient",
    "RecipientResolver",
    "RenderedMessage",
]


@dataclass(frozen=True)
class RenderedMessage:
    """One message, already rendered from a template for one recipient (§B6.3 rule 3)."""

    subject: str
    body: str
    text: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DeliveryResult:
    """What a channel's `send` reports back, for the delivery log (§B6.3 rule 4)."""

    delivered: bool
    error_code: str | None = None
    latency_ms: int | None = None
    retryable: bool = True  # read only when `delivered` is False; every 4xx sets it False (§C6.7)
    skipped: bool = False  # nothing was sent because there is nobody to send to (not a failure)


@dataclass(frozen=True)
class Recipient:
    """Where one member can be reached; held in memory for one send and never logged (§C5.2)."""

    address: str = field(repr=False)
    display_name: str = field(repr=False, default="")
    language: str = "en"


class RecipientResolver(Protocol):
    """Looks a member's contact details up at send time (never stored in the delivery log)."""

    async def resolve(self, member_id: str) -> Recipient | None:
        """The active member's details, or None when they cannot be reached any more."""
        ...


@dataclass(frozen=True)
class ChannelContext:
    """Everything one `send` call needs; built fresh per call, never cached (§B6.3 rule 1)."""

    organization_id: str
    installation: dict[str, Any]
    credentials: MappingProxyType[str, str] = field(
        default_factory=lambda: MappingProxyType[str, str]({}), repr=False
    )
    http: Any | None = None  # an `EgressClient`, or None for a channel that never calls out
    platform: dict[str, Any] = field(default_factory=dict, repr=False)  # installation-wide settings
    recipients: RecipientResolver | None = field(default=None, repr=False)


class NotificationChannel(ABC):
    """One channel implementation: in-app, email, webhook, or a third-party package (§B6.3 rule 9)."""

    INTERFACE_VERSION: ClassVar[str] = "1.0"

    key: ClassVar[str]
    display_name: ClassVar[str] = ""  # shown in the admin UI; falls back to `key`
    accepts_allowed_hosts: ClassVar[bool] = False  # True for webhook-type channels (§B6.3)
    config_schema: ClassVar[type[BaseModel]]
    secret_fields: ClassVar[tuple[str, ...]] = ()
    platform_secret_fields: ClassVar[tuple[str, ...]] = ()  # `secret://` refs in platform config
    egress_hosts: ClassVar[tuple[str, ...]] = ()

    def egress_allowlist(self, platform: dict[str, Any]) -> tuple[str, ...]:
        """Hosts this channel may reach, given the installation-wide platform settings."""
        return self.egress_hosts

    @classmethod
    def allowed_hosts_for(cls, settings: dict[str, Any]) -> list[str]:
        """Hosts the installation's own settings imply (a webhook's destination); added when saved."""
        return []

    def accepts_event(self, settings: dict[str, Any], event_type: str) -> bool:
        """False when this installation does not want `event_type` (nothing is queued for it)."""
        return True

    def build_message_data(
        self,
        settings: dict[str, Any],
        event_type: str,
        event_data: dict[str, Any],
        occurred_at: datetime | None,
        *,
        allow_personal: bool,
    ) -> dict[str, Any] | None:
        """What a pending delivery stores for this channel; None means the template's declared fields."""
        return None

    @abstractmethod
    async def send(
        self, ctx: ChannelContext, target: str, message: RenderedMessage, idempotency_key: str
    ) -> DeliveryResult:
        """Deliver `message` to `target` under `ctx`; never raises for an ordinary send failure.

        `target` is what `notification_deliveries.target` records - pseudonymous (a member id or a
        masked host), never an email address, phone number or name (this plan's P6-00 migration,
        following §C4.6). The member id is always enough: `email` and `webhook` resolve the real
        address or URL from the member's own record or the channel installation when they send.
        """

    @abstractmethod
    async def health(self, ctx: ChannelContext) -> dict[str, Any]:
        """Report whether this channel works for `ctx.organization_id` right now."""
