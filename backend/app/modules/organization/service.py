# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Organization structure and access service layer (§B5.2, §B5.5, §C4.3, M1.4-T2, M1.4-T4)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import asyncpg

from app.core.db import Pool, platform_transaction, tenant_transaction
from app.core.ids import uuid7
from app.core.scope import MemberContext, default_scope_resolver
from app.modules.audit.service import record_audit_event
from app.modules.organization.errors import (
    LocationConflictError,
    LocationDeleteBlockedError,
    LocationInvalidMoveError,
    LocationNotFoundError,
    LocationVersionConflictError,
    OrgUnitArchiveBlockedError,
    OrgUnitConflictError,
    OrgUnitInvalidMoveError,
    OrgUnitNotFoundError,
    OrgUnitVersionConflictError,
    TeamArchiveBlockedError,
    TeamConflictError,
    TeamMemberConflictError,
    TeamMemberNotFoundError,
    TeamNotFoundError,
    TeamVersionConflictError,
)
from app.modules.organization.events import (
    LOCATION_CREATED,
    LOCATION_DELETED,
    LOCATION_MOVED,
    LOCATION_UPDATED,
    ORG_UNIT_ARCHIVED,
    ORG_UNIT_CREATED,
    ORG_UNIT_MOVED,
    ORG_UNIT_UPDATED,
    TEAM_ARCHIVED,
    TEAM_CREATED,
    TEAM_MEMBER_ADDED,
    TEAM_MEMBER_REMOVED,
    TEAM_MEMBER_UPDATED,
    TEAM_UPDATED,
)
from app.modules.organization.repository import (
    LocationRepository,
    OrgUnitRepository,
    TeamMemberRepository,
    TeamRepository,
    to_ltree_label,
)
from app.modules.organization.schemas import (
    LocationCreate,
    LocationMove,
    LocationRead,
    LocationUpdate,
    OrgUnitArchive,
    OrgUnitCreate,
    OrgUnitMove,
    OrgUnitRead,
    OrgUnitUpdate,
    TeamArchive,
    TeamCreate,
    TeamMemberAdd,
    TeamMemberRead,
    TeamMemberUpdate,
    TeamRead,
    TeamUpdate,
)

type DbConn = asyncpg.Connection[asyncpg.Record] | asyncpg.pool.PoolConnectionProxy[asyncpg.Record]

ADMIN_ROLE_KEY = "admin"
ROOT_ORG_UNIT_CODE = "root"
ROOT_ORG_UNIT_TYPE = "root"

org_unit_repo = OrgUnitRepository()
location_repo = LocationRepository()
team_repo = TeamRepository()
team_member_repo = TeamMemberRepository()

__all__ = [
    "ADMIN_ROLE_KEY",
    "ROOT_ORG_UNIT_CODE",
    "ROOT_ORG_UNIT_TYPE",
    "OrganizationCreated",
    "add_team_member",
    "archive_org_unit",
    "archive_team",
    "create_location",
    "create_org_unit",
    "create_organization",
    "create_team",
    "delete_location",
    "find_organization_id_by_slug",
    "get_location",
    "get_org_unit",
    "get_team",
    "list_locations",
    "list_org_units",
    "list_team_members",
    "list_teams",
    "move_location",
    "move_org_unit",
    "remove_team_member",
    "update_location",
    "update_org_unit",
    "update_team",
    "update_team_member",
]


@dataclass(frozen=True)
class OrganizationCreated:
    organization_id: UUID
    admin_member_id: UUID | None
    created: bool
    """False when the slug already existed: an idempotent no-op, not an error."""


async def find_organization_id_by_slug(conn: DbConn, slug: str) -> UUID | None:
    """Look a slug up before the organization's id is known (platform-level, no tenant context)."""
    result: UUID | None = await conn.fetchval("SELECT platform.find_organization_id($1)", slug)
    return result


async def create_organization(
    pool: Pool,
    *,
    slug: str,
    name: str,
    admin_email: str,
    idp_organization_id: str,
    domain_key: str = "generic",
    settings: dict[str, Any] | None = None,
) -> OrganizationCreated:
    """Create an organization, its root org unit and invited first admin in one transaction.

    Idempotent on `slug`: a second call with an existing slug changes nothing and returns
    `created=False` with the existing organization id (and the matching admin's member id, if an
    admin with `admin_email` already exists in it).
    """
    async with platform_transaction(pool) as conn:
        existing_id = await find_organization_id_by_slug(conn, slug)
    if existing_id is not None:
        async with tenant_transaction(pool, existing_id) as conn:
            admin_id: UUID | None = await conn.fetchval(
                "SELECT id FROM public.members WHERE organization_id = $1 AND email = $2",
                existing_id,
                admin_email,
            )
        return OrganizationCreated(existing_id, admin_id, created=False)

    org_id, unit_id, admin_id = uuid7(), uuid7(), uuid7()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.organizations "
            "(id, slug, name, idp_organization_id, domain_key, settings) "
            "VALUES ($1, $2, $3, $4, $5, $6::jsonb)",
            org_id,
            slug,
            name,
            idp_organization_id,
            domain_key,
            json.dumps(settings or {}),
        )
        await conn.execute(
            "INSERT INTO public.org_units (id, organization_id, parent_id, path, type, code, name) "
            "VALUES ($1, $2, NULL, $3::ltree, $4, $3, $5)",
            unit_id,
            org_id,
            ROOT_ORG_UNIT_CODE,
            ROOT_ORG_UNIT_TYPE,
            name,
        )
        await conn.execute(
            "INSERT INTO public.members "
            "(id, organization_id, idp_subject, email, display_name, primary_org_unit_id, status) "
            "VALUES ($1, $2, $3, $4, $4, $5, 'invited')",
            admin_id,
            org_id,
            _pending_idp_subject(admin_email),
            admin_email,
            unit_id,
        )
        await conn.execute(
            "INSERT INTO public.role_grants "
            "(id, organization_id, member_id, role_key, scope_type, source) "
            "VALUES ($1, $2, $3, $4, 'organization', 'manual')",
            uuid7(),
            org_id,
            admin_id,
            ADMIN_ROLE_KEY,
        )
        await record_audit_event(
            conn,
            organization_id=org_id,
            action="organization.create",
            entity_type="organization",
            entity_id=org_id,
            after_state={"slug": slug, "organization_name": name, "email": admin_email},
        )
        await conn.execute(
            "INSERT INTO public.outbox "
            "(id, organization_id, event_type, aggregate_type, aggregate_id, payload) "
            "VALUES ($1, $2, 'organization.created', 'organization', $3, $4::jsonb)",
            uuid7(),
            org_id,
            org_id,
            json.dumps({"slug": slug}),
        )
    return OrganizationCreated(org_id, admin_id, created=True)


def _pending_idp_subject(admin_email: str) -> str:
    """Placeholder until the invited admin's first sign-in links the real IdP subject (P5-03)."""
    return f"pending-invite:{admin_email}"


# ==============================================================================
# Org Unit Service
# ==============================================================================


async def create_org_unit(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    data: OrgUnitCreate,
    request_id: str | None = None,
) -> OrgUnitRead:
    async with tenant_transaction(pool, organization_id) as conn:
        parent_path: str | None = None
        if data.parent_id is not None:
            parent = await org_unit_repo.get_by_id(
                conn, organization_id=organization_id, unit_id=data.parent_id, for_update=True
            )
            if parent is None:
                raise OrgUnitNotFoundError("Parent organizational unit not found")
            if parent["status"] == "archived":
                raise OrgUnitConflictError("Cannot create a child under an archived organizational unit")
            default_scope_resolver.require(caller, "org_unit.create", {"owner_org_unit_path": parent["path"]})
            parent_path = parent["path"]
        else:
            default_scope_resolver.require(caller, "org_unit.create", None)

        existing = await org_unit_repo.get_by_code(conn, organization_id=organization_id, code=data.code)
        if existing is not None:
            raise OrgUnitConflictError(f"An organizational unit with code {data.code!r} already exists")

        label = to_ltree_label(data.code)
        path = f"{parent_path}.{label}" if parent_path else label
        unit_id = uuid7()

        row = await org_unit_repo.create(
            conn,
            unit_id=unit_id,
            organization_id=organization_id,
            parent_id=data.parent_id,
            path=path,
            unit_type=data.type,
            code=data.code,
            name=data.name,
            manager_member_id=data.manager_member_id,
        )

        after_state = dict(row)
        actor_id = UUID(caller.member_id) if _is_uuid(caller.member_id) else None
        await record_audit_event(
            conn,
            organization_id=organization_id,
            actor_member_id=actor_id,
            action="org_unit.create",
            entity_type="org_unit",
            entity_id=unit_id,
            request_id=request_id,
            after_state=after_state,
        )
        payload = {
            "id": str(unit_id),
            "code": data.code,
            "path": path,
            "parent_id": str(data.parent_id) if data.parent_id else None,
        }
        await conn.execute(
            "INSERT INTO public.outbox "
            "(id, organization_id, event_type, aggregate_type, aggregate_id, payload) "
            "VALUES ($1, $2, $3, 'org_unit', $4, $5::jsonb)",
            uuid7(),
            organization_id,
            ORG_UNIT_CREATED,
            unit_id,
            json.dumps(payload),
        )

    return OrgUnitRead.model_validate(dict(row))


async def get_org_unit(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    unit_id: UUID,
) -> OrgUnitRead:
    async with tenant_transaction(pool, organization_id) as conn:
        row = await org_unit_repo.get_by_id(conn, organization_id=organization_id, unit_id=unit_id)
        if row is None or not default_scope_resolver.check_access(
            caller, "org_unit.read", {"owner_org_unit_path": row["path"]}
        ):
            raise OrgUnitNotFoundError()
        return OrgUnitRead.model_validate(dict(row))


async def update_org_unit(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    unit_id: UUID,
    data: OrgUnitUpdate,
    request_id: str | None = None,
) -> OrgUnitRead:
    async with tenant_transaction(pool, organization_id) as conn:
        current = await org_unit_repo.get_by_id(
            conn, organization_id=organization_id, unit_id=unit_id, for_update=True
        )
        if current is None or not default_scope_resolver.check_access(
            caller, "org_unit.update", {"owner_org_unit_path": current["path"]}
        ):
            raise OrgUnitNotFoundError()

        row = await org_unit_repo.update(
            conn,
            organization_id=organization_id,
            unit_id=unit_id,
            version=data.version,
            name=data.name,
            unit_type=data.type,
            manager_member_id=data.manager_member_id,
            clear_manager=data.clear_manager,
        )
        if row is None:
            raise OrgUnitVersionConflictError()

        actor_id = UUID(caller.member_id) if _is_uuid(caller.member_id) else None
        await record_audit_event(
            conn,
            organization_id=organization_id,
            actor_member_id=actor_id,
            action="org_unit.update",
            entity_type="org_unit",
            entity_id=unit_id,
            request_id=request_id,
            before_state=dict(current),
            after_state=dict(row),
        )
        await conn.execute(
            "INSERT INTO public.outbox "
            "(id, organization_id, event_type, aggregate_type, aggregate_id, payload) "
            "VALUES ($1, $2, $3, 'org_unit', $4, $5::jsonb)",
            uuid7(),
            organization_id,
            ORG_UNIT_UPDATED,
            unit_id,
            json.dumps({"id": str(unit_id), "name": row["name"], "type": row["type"]}),
        )

    return OrgUnitRead.model_validate(dict(row))


async def move_org_unit(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    unit_id: UUID,
    data: OrgUnitMove,
    request_id: str | None = None,
) -> OrgUnitRead:
    async with tenant_transaction(pool, organization_id) as conn:
        current = await org_unit_repo.get_by_id(
            conn, organization_id=organization_id, unit_id=unit_id, for_update=True
        )
        if current is None or not default_scope_resolver.check_access(
            caller, "org_unit.update", {"owner_org_unit_path": current["path"]}
        ):
            raise OrgUnitNotFoundError()
        if current["parent_id"] is None:
            raise OrgUnitInvalidMoveError("Cannot move the root organizational unit")

        if data.new_parent_id == unit_id:
            raise OrgUnitInvalidMoveError("Cannot move an organizational unit into itself")

        new_parent = await org_unit_repo.get_by_id(
            conn, organization_id=organization_id, unit_id=data.new_parent_id, for_update=True
        )
        if new_parent is None or not default_scope_resolver.check_access(
            caller, "org_unit.update", {"owner_org_unit_path": new_parent["path"]}
        ):
            raise OrgUnitNotFoundError("Destination parent organizational unit not found")
        if new_parent["status"] == "archived":
            raise OrgUnitInvalidMoveError("Cannot move into an archived organizational unit")

        old_path = current["path"]
        new_parent_path = new_parent["path"]
        if new_parent_path == old_path or new_parent_path.startswith(f"{old_path}."):
            raise OrgUnitInvalidMoveError("Cannot move an organizational unit into its own descendant")

        label = to_ltree_label(current["code"])
        new_path = f"{new_parent_path}.{label}"

        row = await org_unit_repo.move(
            conn,
            organization_id=organization_id,
            unit_id=unit_id,
            version=data.version,
            new_parent_id=data.new_parent_id,
            old_path=old_path,
            new_path=new_path,
        )
        if row is None:
            raise OrgUnitVersionConflictError()

        actor_id = UUID(caller.member_id) if _is_uuid(caller.member_id) else None
        await record_audit_event(
            conn,
            organization_id=organization_id,
            actor_member_id=actor_id,
            action="org_unit.moved",
            entity_type="org_unit",
            entity_id=unit_id,
            request_id=request_id,
            before_state={"parent_id": str(current["parent_id"]), "path": old_path},
            after_state={"parent_id": str(data.new_parent_id), "path": new_path},
        )
        payload = {
            "id": str(unit_id),
            "old_path": old_path,
            "new_path": new_path,
            "new_parent_id": str(data.new_parent_id),
        }
        await conn.execute(
            "INSERT INTO public.outbox "
            "(id, organization_id, event_type, aggregate_type, aggregate_id, payload) "
            "VALUES ($1, $2, $3, 'org_unit', $4, $5::jsonb)",
            uuid7(),
            organization_id,
            ORG_UNIT_MOVED,
            unit_id,
            json.dumps(payload),
        )

    return OrgUnitRead.model_validate(dict(row))


async def archive_org_unit(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    unit_id: UUID,
    data: OrgUnitArchive,
    request_id: str | None = None,
) -> OrgUnitRead:
    async with tenant_transaction(pool, organization_id) as conn:
        current = await org_unit_repo.get_by_id(
            conn, organization_id=organization_id, unit_id=unit_id, for_update=True
        )
        if current is None or not default_scope_resolver.check_access(
            caller, "org_unit.archive", {"owner_org_unit_path": current["path"]}
        ):
            raise OrgUnitNotFoundError()
        if current["parent_id"] is None:
            raise OrgUnitArchiveBlockedError("Cannot archive the root organizational unit")

        active_children = await org_unit_repo.count_active_children(
            conn, organization_id=organization_id, unit_id=unit_id
        )
        if active_children > 0:
            raise OrgUnitArchiveBlockedError(
                f"Cannot archive organizational unit with {active_children} active child units "
                f"(blocker: active_children)"
            )

        active_members = await org_unit_repo.count_active_members(
            conn, organization_id=organization_id, unit_id=unit_id
        )
        if active_members > 0:
            raise OrgUnitArchiveBlockedError(
                f"Cannot archive organizational unit with {active_members} active members "
                f"(blocker: active_members)"
            )

        active_teams = await org_unit_repo.count_active_teams(
            conn, organization_id=organization_id, unit_id=unit_id
        )
        if active_teams > 0:
            raise OrgUnitArchiveBlockedError(
                f"Cannot archive organizational unit with {active_teams} active teams (blocker: active_teams)"
            )

        row = await org_unit_repo.archive(
            conn, organization_id=organization_id, unit_id=unit_id, version=data.version
        )
        if row is None:
            raise OrgUnitVersionConflictError()

        actor_id = UUID(caller.member_id) if _is_uuid(caller.member_id) else None
        await record_audit_event(
            conn,
            organization_id=organization_id,
            actor_member_id=actor_id,
            action="org_unit.archive",
            entity_type="org_unit",
            entity_id=unit_id,
            request_id=request_id,
            before_state=dict(current),
            after_state=dict(row),
        )
        await conn.execute(
            "INSERT INTO public.outbox "
            "(id, organization_id, event_type, aggregate_type, aggregate_id, payload) "
            "VALUES ($1, $2, $3, 'org_unit', $4, $5::jsonb)",
            uuid7(),
            organization_id,
            ORG_UNIT_ARCHIVED,
            unit_id,
            json.dumps({"id": str(unit_id), "code": row["code"]}),
        )

    return OrgUnitRead.model_validate(dict(row))


async def list_org_units(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    status: str | None = None,
    parent_id: UUID | None = None,
) -> list[OrgUnitRead]:
    default_scope_resolver.require(caller, "org_unit.read", None)
    scope_filter = default_scope_resolver.resolve_scope_filter(caller, "org_unit.read")
    if scope_filter.is_empty:
        return []
    async with tenant_transaction(pool, organization_id) as conn:
        rows = await org_unit_repo.list(
            conn,
            organization_id=organization_id,
            scope_filter=scope_filter,
            status=status,
            parent_id=parent_id,
        )
        return [OrgUnitRead.model_validate(dict(r)) for r in rows]


# ==============================================================================
# Location Service
# ==============================================================================


async def create_location(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    data: LocationCreate,
    request_id: str | None = None,
) -> LocationRead:
    if not default_scope_resolver.check_access(caller, "location.create", None):
        raise LocationNotFoundError()
    async with tenant_transaction(pool, organization_id) as conn:
        parent_path: str | None = None
        if data.parent_id is not None:
            parent = await location_repo.get_by_id(
                conn, organization_id=organization_id, location_id=data.parent_id, for_update=True
            )
            if parent is None:
                raise LocationNotFoundError("Parent location not found")
            parent_path = parent["path"]

        existing = await location_repo.get_by_code(conn, organization_id=organization_id, code=data.code)
        if existing is not None:
            raise LocationConflictError(f"A location with code {data.code!r} already exists")

        label = to_ltree_label(data.code)
        path = f"{parent_path}.{label}" if parent_path else label
        loc_id = uuid7()

        row = await location_repo.create(
            conn,
            location_id=loc_id,
            organization_id=organization_id,
            parent_id=data.parent_id,
            path=path,
            loc_type=data.type,
            code=data.code,
            name=data.name,
            address=data.address,
        )

        after_state = dict(row)
        if isinstance(row["address"], str):
            after_state["address"] = json.loads(row["address"])
        actor_id = UUID(caller.member_id) if _is_uuid(caller.member_id) else None
        await record_audit_event(
            conn,
            organization_id=organization_id,
            actor_member_id=actor_id,
            action="location.create",
            entity_type="location",
            entity_id=loc_id,
            request_id=request_id,
            after_state=after_state,
        )
        payload = {
            "id": str(loc_id),
            "code": data.code,
            "path": path,
            "parent_id": str(data.parent_id) if data.parent_id else None,
        }
        await conn.execute(
            "INSERT INTO public.outbox "
            "(id, organization_id, event_type, aggregate_type, aggregate_id, payload) "
            "VALUES ($1, $2, $3, 'location', $4, $5::jsonb)",
            uuid7(),
            organization_id,
            LOCATION_CREATED,
            loc_id,
            json.dumps(payload),
        )

    d = dict(row)
    d["address"] = json.loads(d["address"]) if isinstance(d["address"], str) else d["address"]
    return LocationRead.model_validate(d)


async def get_location(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    location_id: UUID,
) -> LocationRead:
    if not default_scope_resolver.check_access(caller, "location.read", None):
        raise LocationNotFoundError()
    async with tenant_transaction(pool, organization_id) as conn:
        row = await location_repo.get_by_id(conn, organization_id=organization_id, location_id=location_id)
        if row is None:
            raise LocationNotFoundError()
        d = dict(row)
        d["address"] = json.loads(d["address"]) if isinstance(d["address"], str) else d["address"]
        return LocationRead.model_validate(d)


async def update_location(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    location_id: UUID,
    data: LocationUpdate,
    request_id: str | None = None,
) -> LocationRead:
    if not default_scope_resolver.check_access(caller, "location.update", None):
        raise LocationNotFoundError()
    async with tenant_transaction(pool, organization_id) as conn:
        current = await location_repo.get_by_id(
            conn, organization_id=organization_id, location_id=location_id, for_update=True
        )
        if current is None:
            raise LocationNotFoundError()

        row = await location_repo.update(
            conn,
            organization_id=organization_id,
            location_id=location_id,
            version=data.version,
            name=data.name,
            loc_type=data.type,
            address=data.address,
        )
        if row is None:
            raise LocationVersionConflictError()

        cur_d = dict(current)
        cur_d["address"] = (
            json.loads(cur_d["address"]) if isinstance(cur_d["address"], str) else cur_d["address"]
        )
        row_d = dict(row)
        row_d["address"] = (
            json.loads(row_d["address"]) if isinstance(row_d["address"], str) else row_d["address"]
        )

        actor_id = UUID(caller.member_id) if _is_uuid(caller.member_id) else None
        await record_audit_event(
            conn,
            organization_id=organization_id,
            actor_member_id=actor_id,
            action="location.update",
            entity_type="location",
            entity_id=location_id,
            request_id=request_id,
            before_state=cur_d,
            after_state=row_d,
        )
        await conn.execute(
            "INSERT INTO public.outbox "
            "(id, organization_id, event_type, aggregate_type, aggregate_id, payload) "
            "VALUES ($1, $2, $3, 'location', $4, $5::jsonb)",
            uuid7(),
            organization_id,
            LOCATION_UPDATED,
            location_id,
            json.dumps({"id": str(location_id), "name": row["name"], "type": row["type"]}),
        )

    return LocationRead.model_validate(row_d)


async def move_location(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    location_id: UUID,
    data: LocationMove,
    request_id: str | None = None,
) -> LocationRead:
    if not default_scope_resolver.check_access(caller, "location.update", None):
        raise LocationNotFoundError()
    async with tenant_transaction(pool, organization_id) as conn:
        current = await location_repo.get_by_id(
            conn, organization_id=organization_id, location_id=location_id, for_update=True
        )
        if current is None:
            raise LocationNotFoundError()

        if data.new_parent_id == location_id:
            raise LocationInvalidMoveError("Cannot move a location into itself")

        old_path = current["path"]
        new_parent_path: str | None = None

        if data.new_parent_id is not None:
            new_parent = await location_repo.get_by_id(
                conn, organization_id=organization_id, location_id=data.new_parent_id, for_update=True
            )
            if new_parent is None:
                raise LocationNotFoundError("Destination parent location not found")
            new_parent_path = new_parent["path"]
            if new_parent_path == old_path or new_parent_path.startswith(f"{old_path}."):
                raise LocationInvalidMoveError("Cannot move a location into its own descendant")

        label = to_ltree_label(current["code"])
        new_path = f"{new_parent_path}.{label}" if new_parent_path else label

        row = await location_repo.move(
            conn,
            organization_id=organization_id,
            location_id=location_id,
            version=data.version,
            new_parent_id=data.new_parent_id,
            old_path=old_path,
            new_path=new_path,
        )
        if row is None:
            raise LocationVersionConflictError()

        row_d = dict(row)
        row_d["address"] = (
            json.loads(row_d["address"]) if isinstance(row_d["address"], str) else row_d["address"]
        )

        actor_id = UUID(caller.member_id) if _is_uuid(caller.member_id) else None
        before_parent = str(current["parent_id"]) if current["parent_id"] else None
        after_parent = str(data.new_parent_id) if data.new_parent_id else None
        await record_audit_event(
            conn,
            organization_id=organization_id,
            actor_member_id=actor_id,
            action="location.moved",
            entity_type="location",
            entity_id=location_id,
            request_id=request_id,
            before_state={"parent_id": before_parent, "path": old_path},
            after_state={"parent_id": after_parent, "path": new_path},
        )
        payload = {
            "id": str(location_id),
            "old_path": old_path,
            "new_path": new_path,
            "new_parent_id": after_parent,
        }
        await conn.execute(
            "INSERT INTO public.outbox "
            "(id, organization_id, event_type, aggregate_type, aggregate_id, payload) "
            "VALUES ($1, $2, $3, 'location', $4, $5::jsonb)",
            uuid7(),
            organization_id,
            LOCATION_MOVED,
            location_id,
            json.dumps(payload),
        )

    return LocationRead.model_validate(row_d)


async def delete_location(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    location_id: UUID,
    version: int,
    request_id: str | None = None,
) -> None:
    if not default_scope_resolver.check_access(caller, "location.delete", None):
        raise LocationNotFoundError()
    async with tenant_transaction(pool, organization_id) as conn:
        current = await location_repo.get_by_id(
            conn, organization_id=organization_id, location_id=location_id, for_update=True
        )
        if current is None:
            raise LocationNotFoundError()

        child_count = await location_repo.count_children(
            conn, organization_id=organization_id, location_id=location_id
        )
        if child_count > 0:
            raise LocationDeleteBlockedError(
                f"Cannot delete location with {child_count} child sub-locations (blocker: child_locations)"
            )

        success = await location_repo.delete(
            conn, organization_id=organization_id, location_id=location_id, version=version
        )
        if not success:
            raise LocationVersionConflictError()

        cur_d = dict(current)
        cur_d["address"] = (
            json.loads(cur_d["address"]) if isinstance(cur_d["address"], str) else cur_d["address"]
        )

        actor_id = UUID(caller.member_id) if _is_uuid(caller.member_id) else None
        await record_audit_event(
            conn,
            organization_id=organization_id,
            actor_member_id=actor_id,
            action="location.delete",
            entity_type="location",
            entity_id=location_id,
            request_id=request_id,
            before_state=cur_d,
        )
        await conn.execute(
            "INSERT INTO public.outbox "
            "(id, organization_id, event_type, aggregate_type, aggregate_id, payload) "
            "VALUES ($1, $2, $3, 'location', $4, $5::jsonb)",
            uuid7(),
            organization_id,
            LOCATION_DELETED,
            location_id,
            json.dumps({"id": str(location_id), "code": current["code"]}),
        )


async def list_locations(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    parent_id: UUID | None = None,
) -> list[LocationRead]:
    default_scope_resolver.require(caller, "location.read", None)
    scope_filter = default_scope_resolver.resolve_scope_filter(caller, "location.read")
    if scope_filter.is_empty:
        return []
    async with tenant_transaction(pool, organization_id) as conn:
        rows = await location_repo.list(
            conn,
            organization_id=organization_id,
            scope_filter=scope_filter,
            parent_id=parent_id,
        )
        results: list[LocationRead] = []
        for r in rows:
            d = dict(r)
            d["address"] = json.loads(d["address"]) if isinstance(d["address"], str) else d["address"]
            results.append(LocationRead.model_validate(d))
        return results


# ==============================================================================
# Team Service
# ==============================================================================


async def create_team(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    data: TeamCreate,
    request_id: str | None = None,
) -> TeamRead:
    async with tenant_transaction(pool, organization_id) as conn:
        if data.owning_org_unit_id is not None:
            ou = await org_unit_repo.get_by_id(
                conn, organization_id=organization_id, unit_id=data.owning_org_unit_id
            )
            if ou is None:
                raise OrgUnitNotFoundError("Owning organizational unit not found")
            default_scope_resolver.require(caller, "team.create", {"owner_org_unit_path": ou["path"]})
        else:
            default_scope_resolver.require(caller, "team.create", None)

        existing = await team_repo.get_by_code(conn, organization_id=organization_id, code=data.code)
        if existing is not None:
            raise TeamConflictError(f"A team with code {data.code!r} already exists")

        team_id = uuid7()
        row = await team_repo.create(
            conn,
            team_id=team_id,
            organization_id=organization_id,
            code=data.code,
            name=data.name,
            team_type=data.type,
            owning_org_unit_id=data.owning_org_unit_id,
            skills=data.skills,
            working_calendar_id=data.working_calendar_id,
        )

        actor_id = UUID(caller.member_id) if _is_uuid(caller.member_id) else None
        await record_audit_event(
            conn,
            organization_id=organization_id,
            actor_member_id=actor_id,
            action="team.create",
            entity_type="team",
            entity_id=team_id,
            request_id=request_id,
            after_state=dict(row),
        )
        payload = {"id": str(team_id), "code": data.code, "name": data.name, "type": data.type}
        await conn.execute(
            "INSERT INTO public.outbox "
            "(id, organization_id, event_type, aggregate_type, aggregate_id, payload) "
            "VALUES ($1, $2, $3, 'team', $4, $5::jsonb)",
            uuid7(),
            organization_id,
            TEAM_CREATED,
            team_id,
            json.dumps(payload),
        )

    return TeamRead.model_validate(dict(row))


async def get_team(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    team_id: UUID,
) -> TeamRead:
    async with tenant_transaction(pool, organization_id) as conn:
        row = await team_repo.get_by_id(conn, organization_id=organization_id, team_id=team_id)
        if row is None:
            raise TeamNotFoundError()

        ou_path: str | None = None
        if row["owning_org_unit_id"] is not None:
            ou = await org_unit_repo.get_by_id(
                conn, organization_id=organization_id, unit_id=row["owning_org_unit_id"]
            )
            if ou:
                ou_path = ou["path"]
        if not default_scope_resolver.check_access(
            caller, "team.read", {"team_id": str(team_id), "owner_org_unit_path": ou_path}
        ):
            raise TeamNotFoundError()
        return TeamRead.model_validate(dict(row))


async def update_team(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    team_id: UUID,
    data: TeamUpdate,
    request_id: str | None = None,
) -> TeamRead:
    async with tenant_transaction(pool, organization_id) as conn:
        current = await team_repo.get_by_id(
            conn, organization_id=organization_id, team_id=team_id, for_update=True
        )
        if current is None:
            raise TeamNotFoundError()

        ou_path: str | None = None
        if current["owning_org_unit_id"] is not None:
            ou = await org_unit_repo.get_by_id(
                conn, organization_id=organization_id, unit_id=current["owning_org_unit_id"]
            )
            if ou:
                ou_path = ou["path"]
        if not default_scope_resolver.check_access(
            caller, "team.update", {"team_id": str(team_id), "owner_org_unit_path": ou_path}
        ):
            raise TeamNotFoundError()

        if data.owning_org_unit_id is not None:
            new_ou = await org_unit_repo.get_by_id(
                conn, organization_id=organization_id, unit_id=data.owning_org_unit_id
            )
            if new_ou is None or not default_scope_resolver.check_access(
                caller, "team.update", {"owner_org_unit_path": new_ou["path"]}
            ):
                raise OrgUnitNotFoundError("Owning organizational unit not found")

        row = await team_repo.update(
            conn,
            organization_id=organization_id,
            team_id=team_id,
            version=data.version,
            name=data.name,
            team_type=data.type,
            owning_org_unit_id=data.owning_org_unit_id,
            clear_owning_org_unit=data.clear_owning_org_unit,
            skills=data.skills,
            working_calendar_id=data.working_calendar_id,
            clear_working_calendar=data.clear_working_calendar,
        )
        if row is None:
            raise TeamVersionConflictError()

        actor_id = UUID(caller.member_id) if _is_uuid(caller.member_id) else None
        await record_audit_event(
            conn,
            organization_id=organization_id,
            actor_member_id=actor_id,
            action="team.update",
            entity_type="team",
            entity_id=team_id,
            request_id=request_id,
            before_state=dict(current),
            after_state=dict(row),
        )
        await conn.execute(
            "INSERT INTO public.outbox "
            "(id, organization_id, event_type, aggregate_type, aggregate_id, payload) "
            "VALUES ($1, $2, $3, 'team', $4, $5::jsonb)",
            uuid7(),
            organization_id,
            TEAM_UPDATED,
            team_id,
            json.dumps({"id": str(team_id), "name": row["name"], "type": row["type"]}),
        )

    return TeamRead.model_validate(dict(row))


async def archive_team(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    team_id: UUID,
    data: TeamArchive,
    request_id: str | None = None,
) -> TeamRead:
    async with tenant_transaction(pool, organization_id) as conn:
        current = await team_repo.get_by_id(
            conn, organization_id=organization_id, team_id=team_id, for_update=True
        )
        if current is None:
            raise TeamNotFoundError()

        ou_path: str | None = None
        if current["owning_org_unit_id"] is not None:
            ou = await org_unit_repo.get_by_id(
                conn, organization_id=organization_id, unit_id=current["owning_org_unit_id"]
            )
            if ou:
                ou_path = ou["path"]
        if not default_scope_resolver.check_access(
            caller, "team.archive", {"team_id": str(team_id), "owner_org_unit_path": ou_path}
        ):
            raise TeamNotFoundError()

        active_members = await team_repo.count_active_members(
            conn, organization_id=organization_id, team_id=team_id
        )
        if active_members > 0:
            raise TeamArchiveBlockedError(
                f"Cannot archive team with {active_members} active members (blocker: active_members)"
            )

        row = await team_repo.archive(
            conn, organization_id=organization_id, team_id=team_id, version=data.version
        )
        if row is None:
            raise TeamVersionConflictError()

        actor_id = UUID(caller.member_id) if _is_uuid(caller.member_id) else None
        await record_audit_event(
            conn,
            organization_id=organization_id,
            actor_member_id=actor_id,
            action="team.archive",
            entity_type="team",
            entity_id=team_id,
            request_id=request_id,
            before_state=dict(current),
            after_state=dict(row),
        )
        await conn.execute(
            "INSERT INTO public.outbox "
            "(id, organization_id, event_type, aggregate_type, aggregate_id, payload) "
            "VALUES ($1, $2, $3, 'team', $4, $5::jsonb)",
            uuid7(),
            organization_id,
            TEAM_ARCHIVED,
            team_id,
            json.dumps({"id": str(team_id), "code": row["code"]}),
        )

    return TeamRead.model_validate(dict(row))


async def list_teams(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    status: str | None = None,
    owning_org_unit_id: UUID | None = None,
) -> list[TeamRead]:
    default_scope_resolver.require(caller, "team.read", None)
    scope_filter = default_scope_resolver.resolve_scope_filter(caller, "team.read")
    if scope_filter.is_empty:
        return []
    async with tenant_transaction(pool, organization_id) as conn:
        rows = await team_repo.list(
            conn,
            organization_id=organization_id,
            scope_filter=scope_filter,
            status=status,
            owning_org_unit_id=owning_org_unit_id,
        )
        return [TeamRead.model_validate(dict(r)) for r in rows]


# ==============================================================================
# Team Member Service
# ==============================================================================


async def add_team_member(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    team_id: UUID,
    data: TeamMemberAdd,
    request_id: str | None = None,
) -> TeamMemberRead:
    async with tenant_transaction(pool, organization_id) as conn:
        team = await team_repo.get_by_id(conn, organization_id=organization_id, team_id=team_id)
        if team is None:
            raise TeamNotFoundError()
        if team["status"] == "archived":
            raise TeamConflictError("Cannot assign members to an archived team")

        ou_path: str | None = None
        if team["owning_org_unit_id"] is not None:
            ou = await org_unit_repo.get_by_id(
                conn, organization_id=organization_id, unit_id=team["owning_org_unit_id"]
            )
            if ou:
                ou_path = ou["path"]
        if not default_scope_resolver.check_access(
            caller, "team.update", {"team_id": str(team_id), "owner_org_unit_path": ou_path}
        ):
            raise TeamNotFoundError()

        member = await conn.fetchrow(
            "SELECT id, status FROM public.members WHERE organization_id = $1 AND id = $2",
            organization_id,
            data.member_id,
        )
        if member is None:
            raise TeamMemberConflictError("Target member does not exist")
        if member["status"] in ("suspended", "left"):
            raise TeamMemberConflictError("Cannot assign suspended or departed members to teams")

        existing = await team_member_repo.get_by_team_and_member(
            conn, organization_id=organization_id, team_id=team_id, member_id=data.member_id
        )
        if existing is not None:
            raise TeamMemberConflictError("Member is already assigned to this team")

        rec_id = uuid7()
        row = await team_member_repo.add(
            conn,
            record_id=rec_id,
            organization_id=organization_id,
            team_id=team_id,
            member_id=data.member_id,
            team_role=data.team_role,
            valid_from=data.valid_from,
            valid_to=data.valid_to,
        )

        actor_id = UUID(caller.member_id) if _is_uuid(caller.member_id) else None
        await record_audit_event(
            conn,
            organization_id=organization_id,
            actor_member_id=actor_id,
            action="team_member.add",
            entity_type="team_member",
            entity_id=rec_id,
            request_id=request_id,
            after_state=dict(row),
        )
        payload = {
            "id": str(rec_id),
            "team_id": str(team_id),
            "member_id": str(data.member_id),
            "team_role": data.team_role,
        }
        await conn.execute(
            "INSERT INTO public.outbox "
            "(id, organization_id, event_type, aggregate_type, aggregate_id, payload) "
            "VALUES ($1, $2, $3, 'team', $4, $5::jsonb)",
            uuid7(),
            organization_id,
            TEAM_MEMBER_ADDED,
            team_id,
            json.dumps(payload),
        )

    return TeamMemberRead.model_validate(dict(row))


async def update_team_member(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    team_id: UUID,
    member_id: UUID,
    data: TeamMemberUpdate,
    request_id: str | None = None,
) -> TeamMemberRead:
    async with tenant_transaction(pool, organization_id) as conn:
        team = await team_repo.get_by_id(conn, organization_id=organization_id, team_id=team_id)
        if team is None:
            raise TeamNotFoundError()

        ou_path: str | None = None
        if team["owning_org_unit_id"] is not None:
            ou = await org_unit_repo.get_by_id(
                conn, organization_id=organization_id, unit_id=team["owning_org_unit_id"]
            )
            if ou:
                ou_path = ou["path"]
        if not default_scope_resolver.check_access(
            caller, "team.update", {"team_id": str(team_id), "owner_org_unit_path": ou_path}
        ):
            raise TeamNotFoundError()

        current = await team_member_repo.get_by_team_and_member(
            conn, organization_id=organization_id, team_id=team_id, member_id=member_id
        )
        if current is None:
            raise TeamMemberNotFoundError()

        row = await team_member_repo.update(
            conn,
            organization_id=organization_id,
            team_id=team_id,
            member_id=member_id,
            team_role=data.team_role,
            valid_to=data.valid_to,
        )
        if row is None:
            raise TeamMemberNotFoundError()

        actor_id = UUID(caller.member_id) if _is_uuid(caller.member_id) else None
        await record_audit_event(
            conn,
            organization_id=organization_id,
            actor_member_id=actor_id,
            action="team_member.update",
            entity_type="team_member",
            entity_id=row["id"],
            request_id=request_id,
            before_state=dict(current),
            after_state=dict(row),
        )
        payload = {
            "id": str(row["id"]),
            "team_id": str(team_id),
            "member_id": str(member_id),
            "team_role": row["team_role"],
        }
        await conn.execute(
            "INSERT INTO public.outbox "
            "(id, organization_id, event_type, aggregate_type, aggregate_id, payload) "
            "VALUES ($1, $2, $3, 'team', $4, $5::jsonb)",
            uuid7(),
            organization_id,
            TEAM_MEMBER_UPDATED,
            team_id,
            json.dumps(payload),
        )

    return TeamMemberRead.model_validate(dict(row))


async def remove_team_member(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    team_id: UUID,
    member_id: UUID,
    request_id: str | None = None,
) -> None:
    async with tenant_transaction(pool, organization_id) as conn:
        team = await team_repo.get_by_id(conn, organization_id=organization_id, team_id=team_id)
        if team is None:
            raise TeamNotFoundError()

        ou_path: str | None = None
        if team["owning_org_unit_id"] is not None:
            ou = await org_unit_repo.get_by_id(
                conn, organization_id=organization_id, unit_id=team["owning_org_unit_id"]
            )
            if ou:
                ou_path = ou["path"]
        if not default_scope_resolver.check_access(
            caller, "team.update", {"team_id": str(team_id), "owner_org_unit_path": ou_path}
        ):
            raise TeamNotFoundError()

        current = await team_member_repo.get_by_team_and_member(
            conn, organization_id=organization_id, team_id=team_id, member_id=member_id
        )
        if current is None:
            raise TeamMemberNotFoundError()

        await team_member_repo.remove(
            conn, organization_id=organization_id, team_id=team_id, member_id=member_id
        )

        actor_id = UUID(caller.member_id) if _is_uuid(caller.member_id) else None
        await record_audit_event(
            conn,
            organization_id=organization_id,
            actor_member_id=actor_id,
            action="team_member.remove",
            entity_type="team_member",
            entity_id=current["id"],
            request_id=request_id,
            before_state=dict(current),
        )
        payload = {"team_id": str(team_id), "member_id": str(member_id)}
        await conn.execute(
            "INSERT INTO public.outbox "
            "(id, organization_id, event_type, aggregate_type, aggregate_id, payload) "
            "VALUES ($1, $2, $3, 'team', $4, $5::jsonb)",
            uuid7(),
            organization_id,
            TEAM_MEMBER_REMOVED,
            team_id,
            json.dumps(payload),
        )


async def list_team_members(
    pool: Pool,
    *,
    organization_id: UUID,
    caller: MemberContext,
    team_id: UUID,
) -> list[TeamMemberRead]:
    async with tenant_transaction(pool, organization_id) as conn:
        team = await team_repo.get_by_id(conn, organization_id=organization_id, team_id=team_id)
        if team is None:
            raise TeamNotFoundError()

        ou_path: str | None = None
        if team["owning_org_unit_id"] is not None:
            ou = await org_unit_repo.get_by_id(
                conn, organization_id=organization_id, unit_id=team["owning_org_unit_id"]
            )
            if ou:
                ou_path = ou["path"]
        if not default_scope_resolver.check_access(
            caller, "team.read", {"team_id": str(team_id), "owner_org_unit_path": ou_path}
        ):
            raise TeamNotFoundError()

        rows = await team_member_repo.list_by_team(conn, organization_id=organization_id, team_id=team_id)
        return [TeamMemberRead.model_validate(dict(r)) for r in rows]


def _is_uuid(val: str) -> bool:
    try:
        UUID(val)
        return True
    except ValueError:
        return False
