# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Component API schemas (§B8.1, §C1.3, M2.1-T6, P8-09)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["ComponentAttach", "ComponentChildRead", "ComponentDetach", "ComponentLinkRead"]


class ComponentAttach(BaseModel):
    model_config = ConfigDict(extra="forbid")

    child_asset_id: UUID
    version: int = Field(ge=1, description="Current version of the parent asset (optimistic concurrency)")


class ComponentDetach(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1, description="Current version of the parent asset (optimistic concurrency)")


class ComponentLinkRead(BaseModel):
    """The result of an attach or detach; both assets' versions moved forward."""

    component_id: UUID
    parent_asset_id: UUID
    child_asset_id: UUID
    attached_at: datetime
    detached_at: datetime | None
    parent_version: int
    child_version: int


class ComponentChildRead(BaseModel):
    component_id: UUID
    child_asset_id: UUID
    tag: str
    name: str
    status: str
    attached_at: datetime
    detached_at: datetime | None
