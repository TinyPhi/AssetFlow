# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Install, configure, disable and inspect notification channels (§B6.3 rules 1, 2, 4, 6, D17).

Every write has its audit event and outbox row in the same transaction. Secret values go to the
credential store (OpenBao) and nowhere else: the row keeps only the reference and the names of the
secret fields that have a value, so neither a response nor an audit diff can contain one. No call to
a channel's destination is made here (a test send would be an external call inside a request).
"""

from __future__ import annotations

import ipaddress
import json
import re
from collections.abc import Iterable
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from app.channels.base import NotificationChannel
from app.channels.credentials import ChannelCredentialStore
from app.channels.egress import is_blocked_address
from app.channels.registry import ChannelRegistry
from app.core import clock
from app.core.db import Connection
from app.core.ids import uuid7
from app.core.problems import FieldError, NotFoundError, ValidationFailedError
from app.modules.audit.service import record_audit_event
from app.modules.notifications import repository
from app.modules.notifications.channel_schemas import (
    AvailableChannel,
    InstallationCreate,
    InstallationRead,
    InstallationUpdate,
    SecretState,
)
from app.modules.notifications.errors import (
    ChannelAlreadyInstalledError,
    ChannelVersionConflictError,
    DeliveryNotDeadLetteredError,
)

__all__ = [
    "available_channels",
    "get_installation",
    "install",
    "list_deliveries",
    "list_installations",
    "normalize_hosts",
    "requeue_dead_letter",
    "set_enabled",
    "update",
]

_HOST = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)


def _invalid(field: str, message: str) -> ValidationFailedError:
    return ValidationFailedError(errors=[FieldError(field=field, message=message)])


def normalize_hosts(hosts: Iterable[str]) -> list[str]:
    """Lower-case host names only: no wildcard, port, path, or address in a private range (§B6.3 rule 2)."""
    cleaned: set[str] = set()
    for raw in hosts:
        host = raw.strip().lower().rstrip(".")
        if "*" in host or _HOST.match(host) is None:
            raise _invalid(
                "body.allowed_hosts",
                "Each allowed host must be a plain host name (no wildcard, port or path).",
            )
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            if is_blocked_address(host):
                raise _invalid(
                    "body.allowed_hosts", "An allowed host must not be a private or reserved address."
                )
        cleaned.add(host)
    return sorted(cleaned)


def _channel(
    registry: ChannelRegistry, key: str, field: str = "body.channel_key"
) -> type[NotificationChannel]:
    channel = registry.get(key)
    if channel is None:
        raise _invalid(field, "This channel is not available.")
    return channel


def _validated_settings(
    channel: type[NotificationChannel], settings: dict[str, Any], present_secrets: dict[str, str]
) -> dict[str, Any]:
    """The settings the channel accepts, without its secret fields (those never reach the database)."""
    try:
        model = channel.config_schema.model_validate({**settings, **present_secrets})
    except ValidationError as exc:
        errors = [
            FieldError(field="body.settings." + ".".join(str(p) for p in e["loc"]), message=str(e["msg"]))
            for e in exc.errors()
        ]
        raise ValidationFailedError(errors=errors) from exc
    return model.model_dump(mode="json", exclude=set(channel.secret_fields))


def _json(value: Any) -> dict[str, Any]:
    return json.loads(value) if isinstance(value, str) else dict(value or {})


def _public_state(row: Any) -> dict[str, Any]:
    """What an audit diff or an outbox payload may show of an installation: never a reference or value."""
    return {
        "id": str(row["id"]),
        "channel_key": row["channel_key"],
        "display_name": row["display_name"],
        "settings": _json(row["settings"]),
        "enabled": row["enabled"],
        "allowed_hosts": list(row["allowed_hosts"]),
        "allow_personal_data": row["allow_personal_data"],
        "version": row["version"],
        "secret_fields_set": sorted(row["secret_fields_set"]),
    }


def _read(row: Any, registry: ChannelRegistry) -> InstallationRead:
    channel = registry.get(row["channel_key"])
    names = set(channel.secret_fields) if channel is not None else set()
    set_names = set(row["secret_fields_set"])
    return InstallationRead(
        id=row["id"],
        channel_key=row["channel_key"],
        display_name=row["display_name"],
        settings=_json(row["settings"]),
        secrets={name: SecretState(set=name in set_names) for name in sorted(names | set_names)},
        enabled=row["enabled"],
        allowed_hosts=list(row["allowed_hosts"]),
        allow_personal_data=row["allow_personal_data"],
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def _emit(
    conn: Connection,
    *,
    organization_id: UUID,
    actor_member_id: UUID | None,
    request_id: str | None,
    action: str,
    entity_type: str,
    entity_id: UUID,
    before: dict[str, Any] | None,
    after: dict[str, Any],
) -> None:
    """The audit event and the outbox row of one change, in the caller's transaction."""
    await record_audit_event(
        conn,
        organization_id=organization_id,
        actor_member_id=actor_member_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        request_id=request_id,
        before_state=before,
        after_state=after,
    )
    await conn.execute(
        "INSERT INTO public.outbox (id, organization_id, event_type, aggregate_type, aggregate_id, payload) "
        "VALUES ($1, $2, $3, $4, $5, $6::jsonb)",
        uuid7(),
        organization_id,
        action,
        entity_type,
        entity_id,
        json.dumps(after),
    )


# ----------------------------------------------------------------------------------------- reads


def available_channels(registry: ChannelRegistry) -> list[AvailableChannel]:
    """Every channel an organization can install."""
    channels = [registry.get(key) for key in sorted(registry.keys())]
    return [
        AvailableChannel(
            key=c.key,
            display_name=c.display_name or c.key,
            secret_fields=list(c.secret_fields),
            accepts_allowed_hosts=c.accepts_allowed_hosts,
        )
        for c in channels
        if c is not None
    ]


async def list_installations(conn: Connection, registry: ChannelRegistry) -> list[InstallationRead]:
    rows = await conn.fetch("SELECT * FROM public.notification_channels ORDER BY channel_key")
    return [_read(r, registry) for r in rows]


async def get_installation(
    conn: Connection, registry: ChannelRegistry, installation_id: UUID
) -> InstallationRead:
    row = await conn.fetchrow("SELECT * FROM public.notification_channels WHERE id = $1", installation_id)
    if row is None:
        raise NotFoundError()
    return _read(row, registry)


async def list_deliveries(
    conn: Connection,
    *,
    status: str | None = None,
    channel_key: str | None = None,
    since: datetime | None = None,
    after: tuple[datetime, UUID] | None = None,
    limit: int = 20,
) -> tuple[list[Any], str | None]:
    """A page of the delivery log, newest change first, and the cursor of the next page."""
    rows = await conn.fetch(
        "SELECT id, channel_key, event_id, recipient_member_id, target, status, attempts, latency_ms, "
        "error_code, next_retry_at, created_at, updated_at FROM public.notification_deliveries "
        "WHERE ($1::text IS NULL OR status = $1) AND ($2::text IS NULL OR channel_key = $2) "
        "AND ($3::timestamptz IS NULL OR updated_at >= $3) "
        "AND ($4::timestamptz IS NULL OR (updated_at, id) < ($4, $5::uuid)) "
        "ORDER BY updated_at DESC, id DESC LIMIT $6",
        status,
        channel_key,
        since,
        after[0] if after else None,
        after[1] if after else None,
        limit,
    )
    next_cursor = None
    if len(rows) == limit:
        next_cursor = repository.encode_cursor(rows[-1]["updated_at"], rows[-1]["id"])
    return rows, next_cursor


# ---------------------------------------------------------------------------------------- writes


async def install(
    conn: Connection,
    *,
    store: ChannelCredentialStore,
    registry: ChannelRegistry,
    organization_id: UUID,
    actor_member_id: UUID | None,
    data: InstallationCreate,
    request_id: str | None = None,
) -> InstallationRead:
    channel = _channel(registry, data.channel_key)
    unknown = sorted(set(data.secrets) - set(channel.secret_fields))
    if unknown:
        raise _invalid("body.secrets", "This channel has no such secret field.")
    if data.allowed_hosts and not channel.accepts_allowed_hosts:
        raise _invalid("body.allowed_hosts", "This channel does not take allowed hosts.")
    settings = _validated_settings(channel, data.settings, data.secrets)
    hosts = normalize_hosts(data.allowed_hosts)

    channel_id = uuid7()
    row = await conn.fetchrow(
        "INSERT INTO public.notification_channels "
        "(id, organization_id, channel_key, display_name, settings, secret_fields_set, allowed_hosts, "
        "allow_personal_data) VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8) "
        "ON CONFLICT (organization_id, channel_key) DO NOTHING RETURNING *",
        channel_id,
        organization_id,
        data.channel_key,
        data.display_name or channel.display_name or channel.key,
        json.dumps(settings),
        sorted(data.secrets),
        hosts,
        data.allow_personal_data,
    )
    if row is None:
        raise ChannelAlreadyInstalledError()
    if data.secrets:
        ref = await store.write(organization_id, channel_id, data.secrets)
        row = await conn.fetchrow(
            "UPDATE public.notification_channels SET secret_ref = $2 WHERE id = $1 RETURNING *",
            channel_id,
            ref,
        )
    assert row is not None  # noqa: S101 - the row was just written in this transaction
    await _emit(
        conn,
        organization_id=organization_id,
        actor_member_id=actor_member_id,
        request_id=request_id,
        action="notification_channel.installed",
        entity_type="notification_channel",
        entity_id=channel_id,
        before=None,
        after={**_public_state(row), "secrets_changed": sorted(data.secrets)},
    )
    return _read(row, registry)


async def update(
    conn: Connection,
    *,
    store: ChannelCredentialStore,
    registry: ChannelRegistry,
    organization_id: UUID,
    actor_member_id: UUID | None,
    installation_id: UUID,
    data: InstallationUpdate,
    request_id: str | None = None,
) -> InstallationRead:
    current = await conn.fetchrow(
        "SELECT * FROM public.notification_channels WHERE id = $1 FOR UPDATE", installation_id
    )
    if current is None:
        raise NotFoundError()
    if current["version"] != data.version:
        raise ChannelVersionConflictError()
    channel = _channel(registry, current["channel_key"], "path.installation_id")

    changes = data.secrets or {}
    if set(changes) - set(channel.secret_fields):
        raise _invalid("body.secrets", "This channel has no such secret field.")
    if data.allowed_hosts and not channel.accepts_allowed_hosts:
        raise _invalid("body.allowed_hosts", "This channel does not take allowed hosts.")

    set_before = set(current["secret_fields_set"])
    set_after = (set_before | {k for k, v in changes.items() if v is not None}) - {
        k for k, v in changes.items() if v is None
    }
    settings = _json(current["settings"]) if data.settings is None else data.settings
    # Validate the whole object a send would see; a secret that stays set counts as present.
    present = {name: "set" for name in set_after if name not in changes}
    present.update({k: v for k, v in changes.items() if v is not None})
    settings = _validated_settings(channel, settings, present)

    secret_ref = current["secret_ref"]
    if changes:
        if secret_ref is None:
            secret_ref = await store.write(
                organization_id, installation_id, {k: v for k, v in changes.items() if v is not None}
            )
        else:
            await store.change(secret_ref, changes)

    hosts = (
        list(current["allowed_hosts"]) if data.allowed_hosts is None else normalize_hosts(data.allowed_hosts)
    )
    row = await conn.fetchrow(
        "UPDATE public.notification_channels SET display_name = $3, settings = $4::jsonb, secret_ref = $5, "
        "secret_fields_set = $6, allowed_hosts = $7, allow_personal_data = $8, version = version + 1, "
        "updated_at = $9 WHERE id = $1 AND organization_id = $2 RETURNING *",
        installation_id,
        organization_id,
        data.display_name or current["display_name"],
        json.dumps(settings),
        secret_ref,
        sorted(set_after),
        hosts,
        current["allow_personal_data"] if data.allow_personal_data is None else data.allow_personal_data,
        clock.now(),
    )
    assert row is not None  # noqa: S101 - the row was locked above
    await _emit(
        conn,
        organization_id=organization_id,
        actor_member_id=actor_member_id,
        request_id=request_id,
        action="notification_channel.updated",
        entity_type="notification_channel",
        entity_id=installation_id,
        before=_public_state(current),
        after={**_public_state(row), "secrets_changed": sorted(changes)},
    )
    return _read(row, registry)


async def set_enabled(
    conn: Connection,
    *,
    registry: ChannelRegistry,
    organization_id: UUID,
    actor_member_id: UUID | None,
    installation_id: UUID,
    enabled: bool,
    request_id: str | None = None,
) -> InstallationRead:
    """The kill switch: takes effect on the sender's next claim, deletes nothing (§B6.3 rule 6)."""
    current = await conn.fetchrow(
        "SELECT * FROM public.notification_channels WHERE id = $1 FOR UPDATE", installation_id
    )
    if current is None:
        raise NotFoundError()
    if current["enabled"] == enabled:
        return _read(current, registry)
    row = await conn.fetchrow(
        "UPDATE public.notification_channels SET enabled = $3, version = version + 1, updated_at = $4 "
        "WHERE id = $1 AND organization_id = $2 RETURNING *",
        installation_id,
        organization_id,
        enabled,
        clock.now(),
    )
    assert row is not None  # noqa: S101 - the row was locked above
    await _emit(
        conn,
        organization_id=organization_id,
        actor_member_id=actor_member_id,
        request_id=request_id,
        action="notification_channel.enabled" if enabled else "notification_channel.disabled",
        entity_type="notification_channel",
        entity_id=installation_id,
        before=_public_state(current),
        after=_public_state(row),
    )
    return _read(row, registry)


async def requeue_dead_letter(
    conn: Connection,
    *,
    organization_id: UUID,
    actor_member_id: UUID | None,
    delivery_id: UUID,
    request_id: str | None = None,
) -> Any:
    """Send a dead-lettered delivery again: back to `pending` with its attempts reset (DLQ runbook)."""
    current = await conn.fetchrow(
        "SELECT id, channel_key, status, attempts, error_code FROM public.notification_deliveries "
        "WHERE id = $1 FOR UPDATE",
        delivery_id,
    )
    if current is None:
        raise NotFoundError()
    if current["status"] != "dead_lettered":
        raise DeliveryNotDeadLetteredError()
    row = await conn.fetchrow(
        "UPDATE public.notification_deliveries SET status = 'pending', attempts = 0, error_code = NULL, "
        "next_retry_at = NULL, claimed_by = NULL, claimed_at = NULL, updated_at = $2 WHERE id = $1 "
        "RETURNING id, channel_key, event_id, recipient_member_id, target, status, attempts, latency_ms, "
        "error_code, next_retry_at, created_at, updated_at",
        delivery_id,
        clock.now(),
    )
    assert row is not None  # noqa: S101 - the row was locked above
    await _emit(
        conn,
        organization_id=organization_id,
        actor_member_id=actor_member_id,
        request_id=request_id,
        action="notification_delivery.requeued",
        entity_type="notification_delivery",
        entity_id=delivery_id,
        before={
            "status": current["status"],
            "attempts": current["attempts"],
            "error_code": current["error_code"],
        },
        after={"status": "pending", "attempts": 0, "channel_key": current["channel_key"]},
    )
    return row
