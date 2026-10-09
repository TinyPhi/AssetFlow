# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Component service: list, attach, detach (§B8.1, M2.1-T6, P8-09).

Attach and detach lock both asset rows in id order inside one transaction, check `asset.update` on
both assets, and bump the version of both (each side's `parent` / `component_count` changed). The
`version` in the request is the parent's. Each change writes an audit event for *each* of the two
assets (so both timelines show it) and one outbox row. Moving a parent's components with it is
`components.cascade`, called from the asset edit.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.core.db import Pool, tenant_transaction
from app.core.problems import FieldError, PermissionDeniedError, ScopeDeniedError, ValidationFailedError
from app.core.scope import MemberContext, default_scope_resolver
from app.modules.assets import service as asset_service
from app.modules.assets.components.cascade import actor_id, asset_resource, write_outbox
from app.modules.assets.components.errors import (
    ComponentAlreadyAttachedError,
    ComponentChildEndedError,
    ComponentCycleError,
    ComponentNotAttachedError,
)
from app.modules.assets.components.repository import ComponentRepository, DbConn
from app.modules.assets.components.schemas import ComponentAttach, ComponentDetach
from app.modules.assets.errors import AssetNotFoundError, AssetVersionConflictError
from app.modules.assets.events import ASSET_COMPONENT_ATTACHED, ASSET_COMPONENT_DETACHED
from app.modules.assets.permissions import READ_PERMISSION, UPDATE_PERMISSION
from app.modules.assets.repository import AssetRepository
from app.modules.audit.service import record_audit_event

__all__ = ["attach_component", "detach_component", "list_components"]

_repo = ComponentRepository()
_asset_repo = AssetRepository()


async def _lock_pair(conn: DbConn, organization_id: UUID, parent_id: UUID, child_id: UUID) -> tuple[Any, Any]:
    """Lock both asset rows in id order (never two transactions waiting on each other)."""
    rows: dict[UUID, Any] = {}
    for asset_id in sorted((parent_id, child_id)):
        rows[asset_id] = await _asset_repo.get_by_id(
            conn, organization_id=organization_id, asset_id=asset_id, for_update=True
        )
    return rows[parent_id], rows[child_id]


def _can(caller: MemberContext, permission: str, row: Any) -> bool:
    return default_scope_resolver.check_access(caller, permission, asset_resource(row))


def _require_parent(caller: MemberContext, parent: Any) -> None:
    """Parent: absent or unreadable is 404; readable but not editable is 403."""
    if parent is None or not _can(caller, READ_PERMISSION, parent):
        raise AssetNotFoundError()
    if not _can(caller, UPDATE_PERMISSION, parent):
        raise ScopeDeniedError(f"Permission {UPDATE_PERMISSION!r} does not cover this asset.")


def _require_child(caller: MemberContext, child: Any) -> None:
    if child is None or not _can(caller, READ_PERMISSION, child):
        raise ValidationFailedError(errors=[FieldError(field="child_asset_id", message="not found")])
    if not _can(caller, UPDATE_PERMISSION, child):
        raise ScopeDeniedError(f"Permission {UPDATE_PERMISSION!r} does not cover the child asset.")


async def _bump(conn: DbConn, organization_id: UUID, row: Any, *, expected_version: int) -> int:
    updated = await _asset_repo.update(
        conn, organization_id=organization_id, asset_id=row["id"], version=expected_version, sets={}
    )
    if updated is None:
        raise AssetVersionConflictError()
    return int(updated["version"])


async def _audit_both(
    conn: DbConn,
    *,
    organization_id: UUID,
    caller: MemberContext,
    action: str,
    parent_id: UUID,
    child_id: UUID,
    request_id: str | None,
) -> None:
    for entity_id, other_key, other_id in (
        (parent_id, "child_asset_id", child_id),
        (child_id, "parent_asset_id", parent_id),
    ):
        await record_audit_event(
            conn,
            organization_id=organization_id,
            actor_member_id=actor_id(caller),
            action=action,
            entity_type="asset",
            entity_id=entity_id,
            request_id=request_id,
            after_state={
                "parent_asset_id": str(parent_id),
                "child_asset_id": str(child_id),
                other_key: str(other_id),
            },
        )


async def list_components(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    asset_id: UUID,
    include_history: bool = False,
) -> list[dict[str, Any]]:
    scope_filter = default_scope_resolver.resolve_scope_filter(caller, READ_PERMISSION)
    async with tenant_transaction(pool, organization_id) as conn:
        parent = await _asset_repo.get_by_id(conn, organization_id=organization_id, asset_id=asset_id)
        if parent is None or not _can(caller, READ_PERMISSION, parent):
            raise AssetNotFoundError()
        return await _repo.list_children(
            conn,
            organization_id=organization_id,
            scope_filter=scope_filter,
            parent_asset_id=asset_id,
            include_history=include_history,
        )


async def attach_component(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    parent_asset_id: UUID,
    data: ComponentAttach,
    request_id: str | None = None,
) -> dict[str, Any]:
    if not default_scope_resolver.has_permission(caller, UPDATE_PERMISSION):
        raise PermissionDeniedError(f"Permission {UPDATE_PERMISSION!r} denied.")
    child_asset_id = data.child_asset_id
    async with tenant_transaction(pool, organization_id) as conn:
        await _repo.lock_attachments(conn, organization_id=organization_id)
        if child_asset_id == parent_asset_id:
            raise ComponentCycleError()
        parent, child = await _lock_pair(conn, organization_id, parent_asset_id, child_asset_id)
        _require_parent(caller, parent)
        _require_child(caller, child)
        if parent["version"] != data.version:
            raise AssetVersionConflictError()

        if child["status"] in await asset_service.ended_statuses(conn, organization_id):
            raise ComponentChildEndedError()
        if await _repo.get_current_for_child(
            conn, organization_id=organization_id, child_asset_id=child_asset_id
        ):
            raise ComponentAlreadyAttachedError()
        if child_asset_id in await _repo.ancestor_ids(
            conn, organization_id=organization_id, asset_id=parent_asset_id
        ):
            raise ComponentCycleError()

        link = await _repo.insert(
            conn,
            organization_id=organization_id,
            parent_asset_id=parent_asset_id,
            child_asset_id=child_asset_id,
        )
        parent_version = await _bump(conn, organization_id, parent, expected_version=parent["version"])
        child_version = await _bump(conn, organization_id, child, expected_version=child["version"])
        await _audit_both(
            conn,
            organization_id=organization_id,
            caller=caller,
            action=ASSET_COMPONENT_ATTACHED,
            parent_id=parent_asset_id,
            child_id=child_asset_id,
            request_id=request_id,
        )
        await write_outbox(
            conn,
            organization_id=organization_id,
            event_type=ASSET_COMPONENT_ATTACHED,
            aggregate_id=parent_asset_id,
            payload={"parent_asset_id": str(parent_asset_id), "child_asset_id": str(child_asset_id)},
        )
        return _link_result(link, parent_version, child_version)


async def detach_component(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    parent_asset_id: UUID,
    child_asset_id: UUID,
    data: ComponentDetach,
    request_id: str | None = None,
) -> dict[str, Any]:
    if not default_scope_resolver.has_permission(caller, UPDATE_PERMISSION):
        raise PermissionDeniedError(f"Permission {UPDATE_PERMISSION!r} denied.")
    async with tenant_transaction(pool, organization_id) as conn:
        parent, child = await _lock_pair(conn, organization_id, parent_asset_id, child_asset_id)
        _require_parent(caller, parent)
        if child is None or not _can(caller, READ_PERMISSION, child):
            raise ComponentNotAttachedError()
        if not _can(caller, UPDATE_PERMISSION, child):
            raise ScopeDeniedError(f"Permission {UPDATE_PERMISSION!r} does not cover the child asset.")
        current = await _repo.get_current_link(
            conn,
            organization_id=organization_id,
            parent_asset_id=parent_asset_id,
            child_asset_id=child_asset_id,
        )
        if current is None:
            raise ComponentNotAttachedError()
        if parent["version"] != data.version:
            raise AssetVersionConflictError()

        link = await _repo.detach(conn, organization_id=organization_id, component_id=current["id"])
        parent_version = await _bump(conn, organization_id, parent, expected_version=parent["version"])
        child_version = await _bump(conn, organization_id, child, expected_version=child["version"])
        await _audit_both(
            conn,
            organization_id=organization_id,
            caller=caller,
            action=ASSET_COMPONENT_DETACHED,
            parent_id=parent_asset_id,
            child_id=child_asset_id,
            request_id=request_id,
        )
        await write_outbox(
            conn,
            organization_id=organization_id,
            event_type=ASSET_COMPONENT_DETACHED,
            aggregate_id=parent_asset_id,
            payload={"parent_asset_id": str(parent_asset_id), "child_asset_id": str(child_asset_id)},
        )
        return _link_result(link, parent_version, child_version)


def _link_result(link: Any, parent_version: int, child_version: int) -> dict[str, Any]:
    return {
        "component_id": link["id"],
        "parent_asset_id": link["parent_asset_id"],
        "child_asset_id": link["child_asset_id"],
        "attached_at": link["attached_at"],
        "detached_at": link["detached_at"],
        "parent_version": parent_version,
        "child_version": child_version,
    }
