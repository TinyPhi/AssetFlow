# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The `webhook` channel: a signed HTTPS POST to a URL the organization chose (§B6.3, M1.5-T5, §C5.8).

The request goes through the egress client only: HTTPS, the URL's host (added to the installation's
allowed hosts when the settings are saved), a public address, the exact address that passed the
check, no redirects. The body is built from a declarative field mapping and serialized once; those
same bytes are signed and sent.

Headers (documented in the channel guide for receivers):

* `X-AssetFlow-Delivery-Id`: the delivery's idempotency key, so a receiver can drop a duplicate;
* `X-AssetFlow-Timestamp`: Unix seconds; a receiver rejects anything older than 5 minutes;
* `X-AssetFlow-Signature`: `sha256=` and the hex HMAC-SHA256, keyed with the signing secret, of
  `<timestamp>.<body>`.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime
from typing import Any, ClassVar
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationInfo, field_validator, model_validator

from app.channels.base import ChannelContext, DeliveryResult, NotificationChannel, RenderedMessage
from app.channels.retry import failure_from_exception, failure_from_status
from app.channels.webhook_mapping import EventCatalog, build_payload, canonical_json, mapping_problems
from app.core import clock

__all__ = ["WebhookChannel", "WebhookSettings", "sign"]

SIGNATURE_HEADER = "X-AssetFlow-Signature"
TIMESTAMP_HEADER = "X-AssetFlow-Timestamp"
DELIVERY_HEADER = "X-AssetFlow-Delivery-Id"


def sign(secret: str, timestamp: str, body: bytes) -> str:
    """`sha256=<hex HMAC-SHA256(secret, timestamp + "." + body)>`."""
    digest = hmac.new(secret.encode("utf-8"), timestamp.encode("ascii") + b"." + body, hashlib.sha256)
    return f"sha256={digest.hexdigest()}"


class WebhookSettings(BaseModel):
    """Per-organization settings of the `webhook` channel (§B6.3)."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(max_length=2000, description="Destination; HTTPS only")
    signing_secret: SecretStr = Field(
        min_length=16, json_schema_extra={"writeOnly": True}, description="Signs every request; write-only"
    )
    events: list[str] = Field(min_length=1, description="Event types to send")
    field_mapping: dict[str, str] = Field(default_factory=dict, description="Target path -> event field")
    include_personal_data: bool = False

    @field_validator("url")
    @classmethod
    def _https(cls, value: str) -> str:
        parts = urlsplit(value)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.fragment
        ):
            raise ValueError("must be an https:// URL with a host and no credentials or fragment")
        return value

    @model_validator(mode="after")
    def _mapping_is_valid(self, info: ValidationInfo) -> WebhookSettings:
        catalog: EventCatalog | None = (info.context or {}).get("event_registry")
        if catalog is None:
            raise ValueError("the event catalog is needed to check events and mapped fields")
        problems = mapping_problems(self.field_mapping, self.events, catalog)
        if problems:
            path, message = problems[0]
            raise ValueError(f"{path}: {message}")
        return self


class WebhookChannel(NotificationChannel):
    """Sends one signed JSON request per delivery."""

    key: ClassVar[str] = "webhook"
    display_name: ClassVar[str] = "Webhook"
    config_schema: ClassVar[type[BaseModel]] = WebhookSettings
    secret_fields: ClassVar[tuple[str, ...]] = ("signing_secret",)

    # ----------------------------------------------------------------- enqueue-time hooks

    @classmethod
    def allowed_hosts_for(cls, settings: dict[str, Any]) -> list[str]:
        """The destination's host, so the installation's allowlist always contains exactly it."""
        host = urlsplit(str(settings.get("url", ""))).hostname
        return [host] if host else []

    def accepts_event(self, settings: dict[str, Any], event_type: str) -> bool:
        return event_type in (settings.get("events") or [])

    def build_message_data(
        self,
        settings: dict[str, Any],
        event_type: str,
        event_data: dict[str, Any],
        occurred_at: datetime | None,
        *,
        allow_personal: bool,
        personal_fields: frozenset[str],
    ) -> dict[str, Any] | None:
        """The mapped fields of this event (personal ones only if allowed), plus when it happened."""
        payload = build_payload(
            settings.get("field_mapping") or {},
            event_data,
            personal_fields=personal_fields,
            allow_personal=allow_personal and bool(settings.get("include_personal_data", False)),
        )
        return {"payload": payload, "occurred_at": occurred_at.isoformat() if occurred_at else None}

    # ------------------------------------------------------------------------------- send

    async def send(
        self, ctx: ChannelContext, target: str, message: RenderedMessage, idempotency_key: str
    ) -> DeliveryResult:
        """POST the signed body; 2xx is delivered, 5xx and timeouts retry, every 4xx does not."""
        started = time.monotonic()
        secret = ctx.credentials.get("signing_secret")
        settings = ctx.installation.get("settings") or {}
        url = settings.get("url")
        if not secret or not url or ctx.http is None:
            return DeliveryResult(False, "webhook.not_configured", retryable=False)
        fields = message.data.get("fields") or {}
        body = canonical_json(
            {
                "event_type": message.data.get("event_type"),
                "event_id": message.data.get("event_id"),
                "occurred_at": fields.get("occurred_at"),
                "organization_id": ctx.organization_id,
                **(fields.get("payload") or {}),
            }
        )
        timestamp = str(int(clock.now().timestamp()))
        headers = {
            "Content-Type": "application/json",
            DELIVERY_HEADER: idempotency_key,
            TIMESTAMP_HEADER: timestamp,
            SIGNATURE_HEADER: sign(secret, timestamp, body),
        }
        try:
            response = await ctx.http.request("POST", str(url), headers=headers, content=body)
        except Exception as exc:  # noqa: BLE001 - classified, never re-raised, the text is not kept
            return failure_from_exception(exc, int((time.monotonic() - started) * 1000))
        latency = int((time.monotonic() - started) * 1000)
        if 200 <= response.status_code < 300:
            return DeliveryResult(delivered=True, latency_ms=latency)
        return failure_from_status(response.status_code, latency)

    # ----------------------------------------------------------------------------- health

    async def health(self, ctx: ChannelContext) -> dict[str, Any]:
        """Valid settings and a public destination; sends nothing (no surprise traffic)."""
        settings = ctx.installation.get("settings") or {}
        parts = urlsplit(str(settings.get("url", "")))
        if not parts.hostname or ctx.http is None:
            return {"healthy": False, "status": "not_configured"}
        try:
            await ctx.http.resolve_checked(parts.hostname, parts.port or 443)
        except Exception:  # noqa: BLE001 - any refusal or lookup failure is "degraded"
            return {"healthy": False, "status": "degraded"}
        return {"healthy": True, "status": "healthy"}
