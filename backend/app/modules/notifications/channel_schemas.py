# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Request and response models of the channel administration API (§B6.3, D17)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "AvailableChannel",
    "DeliveryList",
    "DeliveryRead",
    "InstallationCreate",
    "InstallationRead",
    "InstallationUpdate",
    "SecretState",
]


class SecretState(BaseModel):
    """A secret field as the API shows it: whether a value is stored, never the value (D17)."""

    set: bool


class AvailableChannel(BaseModel):
    """A channel an organization can install."""

    key: str
    display_name: str
    secret_fields: list[str]
    accepts_allowed_hosts: bool


class InstallationCreate(BaseModel):
    """Install a channel; `secrets` are written to OpenBao and never read back."""

    model_config = ConfigDict(extra="forbid")

    channel_key: str = Field(min_length=1, max_length=64)
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    settings: dict[str, Any] = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict)
    allowed_hosts: list[str] = Field(default_factory=list)
    allow_personal_data: bool = False


class InstallationUpdate(BaseModel):
    """A partial update. `settings`, when given, replaces all settings; a secret left out keeps its
    stored value and an explicit `null` clears it."""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    settings: dict[str, Any] | None = None
    secrets: dict[str, str | None] | None = None
    allowed_hosts: list[str] | None = None
    allow_personal_data: bool | None = None


class InstallationRead(BaseModel):
    """An installation. Secret fields appear only as `{"set": true|false}`."""

    id: UUID
    channel_key: str
    display_name: str
    settings: dict[str, Any]
    secrets: dict[str, SecretState]
    enabled: bool
    allowed_hosts: list[str]
    allow_personal_data: bool
    version: int
    created_at: datetime
    updated_at: datetime


class DeliveryRead(BaseModel):
    """One delivery in the log: its channel, state and the outcome of its latest attempt."""

    id: UUID
    channel_key: str
    event_id: UUID
    recipient_member_id: UUID | None
    target: str
    status: str
    attempts: int
    latency_ms: int | None
    error_code: str | None
    next_retry_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DeliveryList(BaseModel):
    """A page of the delivery log."""

    items: list[DeliveryRead]
    next_cursor: str | None
