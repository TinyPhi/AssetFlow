# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Organization settings: read and change, every change audited (§B10, M1.4-T9).

`organizations.settings` is a free-form jsonb column; this module is the only writer, so it is
also what decides the allowed keys (`provisioning`, `locale`, `timezone`, `currency`,
`default_calendar_id`) and validates them. A partial update merges into the existing settings; it
never replaces the whole object, so an unrelated key set by another path is not lost.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import asyncpg

from app.core.ids import uuid7
from app.core.problems import ValidationFailedError
from app.modules.audit.service import record_audit_event
from app.modules.organization.provisioning import PROVISIONING_POLICIES

type DbConn = asyncpg.Connection[asyncpg.Record] | asyncpg.pool.PoolConnectionProxy[asyncpg.Record]

ALLOWED_KEYS = frozenset({"provisioning", "locale", "timezone", "currency", "default_calendar_id"})


async def get_settings(conn: DbConn, organization_id: UUID) -> dict[str, Any]:
    raw = await conn.fetchval("SELECT settings FROM public.organizations WHERE id = $1", organization_id)
    if raw is None:
        return {}
    return json.loads(raw) if isinstance(raw, str) else dict(raw)


async def _validate(conn: DbConn, organization_id: UUID, changes: dict[str, Any]) -> None:
    unknown = sorted(set(changes) - ALLOWED_KEYS)
    if unknown:
        raise ValidationFailedError(f"unknown setting(s): {', '.join(unknown)}")
    if "provisioning" in changes and changes["provisioning"] not in PROVISIONING_POLICIES:
        raise ValidationFailedError(
            f"provisioning must be one of {', '.join(PROVISIONING_POLICIES)}, got {changes['provisioning']!r}"
        )
    for key in ("locale", "timezone", "currency"):
        if key in changes and (not isinstance(changes[key], str) or not changes[key]):
            raise ValidationFailedError(f"{key} must be a non-empty string")
    calendar_id = changes.get("default_calendar_id")
    if calendar_id is not None and "default_calendar_id" in changes:
        if isinstance(calendar_id, str):
            calendar_id = UUID(calendar_id)
        exists = await conn.fetchval(
            "SELECT 1 FROM public.working_calendars WHERE organization_id = $1 AND id = $2",
            organization_id,
            calendar_id,
        )
        if not exists:
            raise ValidationFailedError(
                f"default_calendar_id {calendar_id!r} does not exist in this organization"
            )


async def update_settings(
    conn: DbConn, organization_id: UUID, changes: dict[str, Any], *, actor_member_id: UUID | None = None
) -> dict[str, Any]:
    """Merge `changes` into the organization's settings; writes one audit event with both states."""
    await _validate(conn, organization_id, changes)
    # Normalize to plain JSON types (e.g. a UUID becomes str) before merging, storing or auditing.
    changes = json.loads(json.dumps(changes, default=str))
    before = await get_settings(conn, organization_id)
    after = {**before, **changes}
    await conn.execute(
        "UPDATE public.organizations SET settings = $2::jsonb, updated_at = now() WHERE id = $1",
        organization_id,
        json.dumps(after),
    )
    await record_audit_event(
        conn,
        organization_id=organization_id,
        action="organization.settings_update",
        entity_type="organization",
        entity_id=organization_id,
        actor_member_id=actor_member_id,
        before_state=before,
        after_state=after,
    )
    await conn.execute(
        "INSERT INTO public.outbox (id, organization_id, event_type, aggregate_type, aggregate_id, payload) "
        "VALUES ($1, $2, 'organization.settings_updated', 'organization', $2, '{}'::jsonb)",
        uuid7(),
        organization_id,
    )
    return after
