# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Channel installations, the kill switch and the delivery log (§B6.3, §B4.8.2, M1.5-T6).

Secret fields are write-only: they appear in a response only as `{"set": true|false}` (D17). A
caller without the permission to read gets 404; one without the permission to change gets 403
(§C4.5, §C5.4 rule 5). Nothing here calls a channel's destination.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse

from app.api.v1.caller import request_id, resolve_member
from app.channels.credentials import ChannelCredentialStore
from app.channels.registry import ChannelRegistry, default_registry
from app.channels.schema_export import export_schema, schema_etag
from app.core.db import tenant_transaction
from app.core.envelope import success_response
from app.core.problems import NotFoundError, PermissionDeniedError, ValidationFailedError
from app.core.scope import MemberContext, default_scope_resolver
from app.modules.notifications import channels_service, service
from app.modules.notifications.channel_schemas import (
    DeliveryList,
    DeliveryRead,
    InstallationCreate,
    InstallationUpdate,
)
from app.modules.notifications.errors import ChannelNotFoundError

router = APIRouter(prefix="/notification-channels", tags=["notification-channels"])

READ_CHANNELS = "notification_channel.read"
MANAGE_CHANNELS = "notification_channel.manage"
READ_DELIVERIES = "notification_delivery.read"


def _registry(request: Request) -> ChannelRegistry:
    registry: ChannelRegistry | None = getattr(request.app.state, "channel_registry", None)
    if registry is None:
        registry = default_registry(getattr(request.app.state, "config", None))
        request.app.state.channel_registry = registry
    return registry


def _store(request: Request) -> ChannelCredentialStore:
    return ChannelCredentialStore(request.app.state.registry.secrets)


def _can_read(member: MemberContext, permission: str) -> None:
    if not default_scope_resolver.has_permission(member, permission):
        raise NotFoundError()


def _can_manage(member: MemberContext) -> None:
    if not default_scope_resolver.has_permission(member, MANAGE_CHANNELS):
        raise PermissionDeniedError()


def _actor(member: MemberContext) -> UUID | None:
    try:
        return UUID(member.member_id)
    except ValueError:
        return None


@router.get("", summary="Channels that can be installed")
async def list_available_channels(request: Request) -> dict[str, Any]:
    member = resolve_member(request)
    _can_read(member, READ_CHANNELS)
    channels = channels_service.available_channels(_registry(request))
    return success_response(data=[c.model_dump() for c in channels], request_id=request_id(request))


@router.get("/{key}/schema", summary="A channel's settings as JSON Schema")
async def channel_schema(request: Request, key: str) -> Response:
    """The settings schema the admin form is built from; secret fields are marked write-only."""
    member = resolve_member(request)
    _can_read(member, READ_CHANNELS)
    channel = _registry(request).get(key)
    if channel is None:
        raise ChannelNotFoundError()
    schema = export_schema(channel)
    etag = schema_etag(schema)
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    body = success_response(data=schema, request_id=request_id(request))
    return JSONResponse(body, headers={"ETag": etag})


@router.get("/installations", summary="List the organization's channel installations")
async def list_installations(request: Request) -> dict[str, Any]:
    member = resolve_member(request)
    _can_read(member, READ_CHANNELS)
    async with tenant_transaction(request.app.state.pool, UUID(member.organization_id)) as conn:
        items = await channels_service.list_installations(conn, _registry(request))
    return success_response(data=[i.model_dump(mode="json") for i in items], request_id=request_id(request))


@router.post("/installations", status_code=201, summary="Install a channel")
async def install_channel(request: Request, body: InstallationCreate) -> dict[str, Any]:
    member = resolve_member(request)
    _can_manage(member)
    organization_id = UUID(member.organization_id)
    async with tenant_transaction(request.app.state.pool, organization_id) as conn:
        created = await channels_service.install(
            conn,
            store=_store(request),
            registry=_registry(request),
            organization_id=organization_id,
            actor_member_id=_actor(member),
            data=body,
            request_id=request_id(request),
        )
    return success_response(data=created.model_dump(mode="json"), request_id=request_id(request))


@router.get("/installations/{installation_id}", summary="Read one channel installation")
async def get_installation(request: Request, installation_id: UUID) -> dict[str, Any]:
    member = resolve_member(request)
    _can_read(member, READ_CHANNELS)
    async with tenant_transaction(request.app.state.pool, UUID(member.organization_id)) as conn:
        item = await channels_service.get_installation(conn, _registry(request), installation_id)
    return success_response(data=item.model_dump(mode="json"), request_id=request_id(request))


@router.patch("/installations/{installation_id}", summary="Change a channel installation")
async def update_installation(
    request: Request, installation_id: UUID, body: InstallationUpdate
) -> dict[str, Any]:
    member = resolve_member(request)
    _can_manage(member)
    organization_id = UUID(member.organization_id)
    async with tenant_transaction(request.app.state.pool, organization_id) as conn:
        item = await channels_service.update(
            conn,
            store=_store(request),
            registry=_registry(request),
            organization_id=organization_id,
            actor_member_id=_actor(member),
            installation_id=installation_id,
            data=body,
            request_id=request_id(request),
        )
    return success_response(data=item.model_dump(mode="json"), request_id=request_id(request))


async def _switch(request: Request, installation_id: UUID, *, enabled: bool) -> dict[str, Any]:
    member = resolve_member(request)
    _can_manage(member)
    organization_id = UUID(member.organization_id)
    async with tenant_transaction(request.app.state.pool, organization_id) as conn:
        item = await channels_service.set_enabled(
            conn,
            registry=_registry(request),
            organization_id=organization_id,
            actor_member_id=_actor(member),
            installation_id=installation_id,
            enabled=enabled,
            request_id=request_id(request),
        )
    return success_response(data=item.model_dump(mode="json"), request_id=request_id(request))


@router.post("/installations/{installation_id}/disable", summary="Kill switch: stop sending")
async def disable_installation(request: Request, installation_id: UUID) -> dict[str, Any]:
    return await _switch(request, installation_id, enabled=False)


@router.post("/installations/{installation_id}/enable", summary="Resume sending")
async def enable_installation(request: Request, installation_id: UUID) -> dict[str, Any]:
    return await _switch(request, installation_id, enabled=True)


@router.get("/deliveries", summary="The delivery log")
async def list_deliveries(
    request: Request,
    *,
    status: str | None = None,
    channel: str | None = None,
    since: datetime | None = None,
    after: Annotated[str | None, Query(description="Cursor from a previous page's next_cursor")] = None,
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    member = resolve_member(request)
    _can_read(member, READ_DELIVERIES)
    cursor = None
    if after is not None:
        try:
            cursor = service.decode_cursor(after)
        except (ValueError, TypeError) as exc:
            raise ValidationFailedError(detail="The cursor is not valid.") from exc
    async with tenant_transaction(request.app.state.pool, UUID(member.organization_id)) as conn:
        rows, next_cursor = await channels_service.list_deliveries(
            conn, status=status, channel_key=channel, since=since, after=cursor, limit=limit
        )
    page = DeliveryList(items=[DeliveryRead.model_validate(dict(r)) for r in rows], next_cursor=next_cursor)
    return success_response(data=page.model_dump(mode="json"), request_id=request_id(request))


@router.post("/deliveries/{delivery_id}/requeue", summary="Send a dead-lettered delivery again")
async def requeue_delivery(request: Request, delivery_id: UUID) -> dict[str, Any]:
    member = resolve_member(request)
    _can_manage(member)
    organization_id = UUID(member.organization_id)
    async with tenant_transaction(request.app.state.pool, organization_id) as conn:
        row = await channels_service.requeue_dead_letter(
            conn,
            organization_id=organization_id,
            actor_member_id=_actor(member),
            delivery_id=delivery_id,
            request_id=request_id(request),
        )
    return success_response(
        data=DeliveryRead.model_validate(dict(row)).model_dump(mode="json"), request_id=request_id(request)
    )
