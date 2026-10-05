# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Move a parent's components with it, in the parent's own transaction (§B8.1, M2.1-T6, P8-09).

Called by `app.modules.assets.service.update_asset` when an edit changes the owner org unit or the
location and carries `move_components`. Every current descendant gets the same new owner and/or
location, each as its own versioned update with its own `asset.moved_with_parent` audit event and
outbox row. All descendants are locked in id order first and checked against the caller's scope
before anything is written, so a refusal on any one aborts the whole move (403 `scope.denied`
with the count only, never the ids).
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from app.core.ids import uuid7
from app.core.scope import MemberContext, default_scope_resolver
from app.modules.assets.components.errors import ScopeDeniedError
from app.modules.assets.components.repository import ComponentRepository, DbConn
from app.modules.assets.events import ASSET_MOVED_WITH_PARENT
from app.modules.assets.permissions import UPDATE_PERMISSION
from app.modules.assets.repository import AssetRepository
from app.modules.audit.service import record_audit_event

__all__ = ["asset_resource", "move_descendants", "write_outbox"]

_asset_repo = AssetRepository()
_component_repo = ComponentRepository()


def asset_resource(row: Any) -> dict[str, Any]:
    """The record-level scope-check resource of an asset row from `AssetRepository.get_by_id`."""
    member = row["holder_member_id"]
    team = row["holder_team_id"]
    return {
        "owner_org_unit_path": row["owner_org_unit_path"],
        "team_id": str(team) if team else None,
        "holder_member_id": str(member) if member else None,
    }


def actor_id(caller: MemberContext) -> UUID | None:
    try:
        return UUID(caller.member_id)
    except (ValueError, AttributeError):
        return None


async def write_outbox(
    conn: DbConn,
    *,
    organization_id: UUID,
    event_type: str,
    aggregate_id: UUID,
    payload: dict[str, Any],
) -> None:
    await conn.execute(
        "INSERT INTO public.outbox "
        "(id, organization_id, event_type, aggregate_type, aggregate_id, payload) "
        "VALUES ($1, $2, $3, 'asset', $4, $5::jsonb)",
        uuid7(),
        organization_id,
        event_type,
        aggregate_id,
        json.dumps(payload),
    )


async def move_descendants(
    conn: DbConn,
    *,
    organization_id: UUID,
    caller: MemberContext,
    parent_asset_id: UUID,
    new_owner_org_unit_id: UUID | None,
    set_location: bool,
    new_location_id: UUID | None,
    request_id: str | None,
) -> list[UUID]:
    """Move every current descendant of `parent_asset_id`; returns the ids that changed.

    `new_owner_org_unit_id` is `None` when the owner did not change; `set_location` is `True` when
    the location changed (`new_location_id` may then be `None`, a cleared location).
    The caller already holds `asset.update` on the new owner org unit (checked for the parent).
    """
    descendant_ids = await _component_repo.descendant_ids(
        conn, organization_id=organization_id, asset_id=parent_asset_id
    )
    rows = []
    for asset_id in descendant_ids:  # already in id order: the lock order
        row = await _asset_repo.get_by_id(
            conn, organization_id=organization_id, asset_id=asset_id, for_update=True
        )
        if row is not None:
            rows.append(row)

    denied = sum(
        1
        for row in rows
        if not default_scope_resolver.check_access(caller, UPDATE_PERMISSION, asset_resource(row))
    )
    if denied:
        raise ScopeDeniedError(denied)

    moved: list[UUID] = []
    for row in rows:
        sets: dict[str, Any] = {}
        if new_owner_org_unit_id is not None and row["owner_org_unit_id"] != new_owner_org_unit_id:
            sets["owner_org_unit_id"] = new_owner_org_unit_id
        if set_location and row["location_id"] != new_location_id:
            sets["location_id"] = new_location_id
        if not sets:
            continue
        updated = await _asset_repo.update(
            conn,
            organization_id=organization_id,
            asset_id=row["id"],
            version=row["version"],
            sets=sets,
        )
        assert updated is not None  # noqa: S101 - the row is locked and its version was just read
        await record_audit_event(
            conn,
            organization_id=organization_id,
            actor_member_id=actor_id(caller),
            action=ASSET_MOVED_WITH_PARENT,
            entity_type="asset",
            entity_id=row["id"],
            request_id=request_id,
            before_state={k: _text(row[k]) for k in sets},
            after_state={
                **{k: _text(v) for k, v in sets.items()},
                "moved_with_parent_id": str(parent_asset_id),
            },
        )
        await write_outbox(
            conn,
            organization_id=organization_id,
            event_type=ASSET_MOVED_WITH_PARENT,
            aggregate_id=row["id"],
            payload={
                "id": str(row["id"]),
                "version": updated["version"],
                "parent_asset_id": str(parent_asset_id),
            },
        )
        moved.append(row["id"])
    return moved


def _text(value: Any) -> Any:
    return str(value) if isinstance(value, UUID) else value
