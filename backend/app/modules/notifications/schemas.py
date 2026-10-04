# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Inbox API request and response shapes (M1.5-T3)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["NotificationList", "NotificationRead", "UnreadCount"]


class NotificationRead(BaseModel):
    """One notice, as the inbox API returns it."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_type: str
    template_key: str
    title_key: str
    body: str
    link_entity_type: str | None
    link_entity_id: UUID | None
    read_at: datetime | None
    created_at: datetime
    updated_at: datetime


class NotificationList(BaseModel):
    """A page of the caller's own inbox (§B4.5 cursor pagination)."""

    items: list[NotificationRead]
    next_cursor: str | None = Field(default=None, description="Pass as `after` to fetch the next page")


class UnreadCount(BaseModel):
    """How many of the caller's own notices are unread."""

    unread: int
