# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Request and response models of the member preferences API (§B6.3 rule 7, M1.5-T7)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["PreferenceCell", "PreferenceChange", "PreferenceEvent", "PreferenceMatrix", "PreferencesUpdate"]


class PreferenceCell(BaseModel):
    """One (event type, channel): on or off, its stored version (0 = never changed), and whether locked."""

    channel_key: str
    enabled: bool
    version: int
    locked: bool = Field(description="True for in-app on an event whose notice is mandatory")


class PreferenceEvent(BaseModel):
    """One event type and its channels."""

    event_type: str
    channels: list[PreferenceCell]


class PreferenceMatrix(BaseModel):
    """Every event type the member can receive by every channel installed and enabled (plus in-app)."""

    channels: list[str]
    events: list[PreferenceEvent]


class PreferenceChange(BaseModel):
    """Switch one cell. `version` is the one the caller saw (omit it for a cell never changed before)."""

    model_config = ConfigDict(extra="forbid")

    event_type: str = Field(min_length=1, max_length=128)
    channel_key: str = Field(min_length=1, max_length=64)
    enabled: bool
    version: int | None = Field(default=None, ge=0)


class PreferencesUpdate(BaseModel):
    """A set of changes, applied together or not at all."""

    model_config = ConfigDict(extra="forbid")

    changes: list[PreferenceChange] = Field(min_length=1, max_length=500)
