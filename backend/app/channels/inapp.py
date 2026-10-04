# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The `inapp` channel: writes to the inbox, no external call (§B6.3 `inapp` row)."""

from __future__ import annotations

from typing import Any, ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.channels.base import ChannelContext, DeliveryResult, NotificationChannel, RenderedMessage
from app.core.db import Connection
from app.core.ids import uuid7


class InAppSettings(BaseModel):
    """`inapp` has no per-organization settings (§B6.3)."""

    model_config = ConfigDict(extra="forbid")


class InAppChannel(NotificationChannel):
    """Always installed, no credentials, no egress (writes directly into `notifications`)."""

    key: ClassVar[str] = "inapp"
    config_schema: ClassVar[type[BaseModel]] = InAppSettings
    secret_fields: ClassVar[tuple[str, ...]] = ()
    egress_hosts: ClassVar[tuple[str, ...]] = ()

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    async def send(
        self, ctx: ChannelContext, target: str, message: RenderedMessage, idempotency_key: str
    ) -> DeliveryResult:
        """Insert the notice, deduplicated on `(organization_id, idempotency_key)` (§B6.3 rule 8)."""
        row = await self._conn.fetchrow(
            "INSERT INTO public.notifications "
            "(id, organization_id, member_id, event_type, event_id, template_key, title_key, body, "
            "link_entity_type, link_entity_id, idempotency_key) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11) "
            "ON CONFLICT (organization_id, idempotency_key) DO NOTHING "
            "RETURNING id",
            uuid7(),
            UUID(ctx.organization_id),
            UUID(target),
            message.data.get("event_type", ""),
            _as_uuid(message.data.get("event_id")) or uuid7(),
            message.data.get("template_key", ""),
            message.subject,
            message.body,
            message.data.get("link_entity_type"),
            _as_uuid(message.data.get("link_entity_id")),
            idempotency_key,
        )
        return DeliveryResult(delivered=row is not None)

    async def health(self, ctx: ChannelContext) -> dict[str, Any]:
        return {"healthy": True}


def _as_uuid(value: object) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:
            return None
    return None
