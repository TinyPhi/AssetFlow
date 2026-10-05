# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Audit service: logging, personal value redaction/erasure, and scoped queries (§B10, §1590, §2138)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from app.core.ids import uuid7
from app.core.permissions import ScopeFilter

type DbConn = asyncpg.Connection[asyncpg.Record] | asyncpg.pool.PoolConnectionProxy[asyncpg.Record]
PERSONAL_FIELDS = frozenset(
    {
        "name",
        "first_name",
        "last_name",
        "email",
        "phone",
        "phone_number",
        "ip",
        "ip_address",
        "address",
        "national_id",
    }
)


def redact_personal_fields(state: dict[str, Any] | None, collected: dict[str, str]) -> dict[str, Any] | None:
    if state is None:
        return None
    cleaned: dict[str, Any] = {}
    for k, v in state.items():
        if k.lower() in PERSONAL_FIELDS and v is not None:
            collected[k], cleaned[k] = str(v), "[REDACTED]"
        elif isinstance(v, dict):
            cleaned[k] = redact_personal_fields(v, collected)
        else:
            cleaned[k] = v
    return cleaned


async def record_audit_event(
    conn: DbConn,
    *,
    organization_id: UUID,
    action: str,
    entity_type: str,
    entity_id: UUID,
    actor_member_id: UUID | None = None,
    role_used: str | None = None,
    scope_type: str | None = None,
    scope_id: UUID | None = None,
    request_id: str | None = None,
    client_id: str | None = None,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    personal_values: dict[str, str] | None = None,
    event_id: UUID | None = None,
    created_at: datetime | None = None,
) -> UUID:
    ev_id, ts = event_id or uuid7(), created_at or datetime.now(UTC)
    coll = dict(personal_values or {})
    cb, ca = redact_personal_fields(before_state, coll), redact_personal_fields(after_state, coll)
    jb, ja = (json.dumps(cb) if cb is not None else None), (json.dumps(ca) if ca is not None else None)
    await conn.execute(
        "INSERT INTO public.audit_events (id, organization_id, actor_member_id, action, entity_type, "
        "entity_id, role_used, scope_type, scope_id, request_id, client_id, before_state, after_state, "
        "created_at) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb, $13::jsonb, $14)",
        ev_id,
        organization_id,
        actor_member_id,
        action,
        entity_type,
        entity_id,
        role_used,
        scope_type,
        scope_id,
        request_id,
        client_id,
        jb,
        ja,
        ts,
    )
    for fname, fval in coll.items():
        await conn.execute(
            "INSERT INTO public.audit_personal_values "
            "(id, organization_id, audit_event_id, field_name, field_value, created_at) "
            "VALUES ($1, $2, $3, $4, $5, $6)",
            uuid4(),
            organization_id,
            ev_id,
            fname,
            fval,
            ts,
        )
    return ev_id


async def erase_personal_values(
    conn: DbConn, *, organization_id: UUID, audit_event_id: UUID | None = None, field_name: str | None = None
) -> int:
    clauses = ["organization_id = $1"]
    args: list[Any] = [organization_id]
    if audit_event_id is not None:
        args.append(audit_event_id)
        clauses.append(f"audit_event_id = ${len(args)}")
    if field_name is not None:
        args.append(field_name)
        clauses.append(f"field_name = ${len(args)}")
    query = f"DELETE FROM public.audit_personal_values WHERE {' AND '.join(clauses)}"  # nosec B608 # noqa: S608
    res = await conn.execute(query, *args)
    return int(res.split(" ")[-1]) if res else 0


def _build_scope_condition(scope_filter: ScopeFilter, args: list[Any]) -> str | None:
    conds: list[str] = []
    if scope_filter.member_id:
        try:
            args.append(UUID(scope_filter.member_id))
            conds.append(f"actor_member_id = ${len(args)}")
        except ValueError:
            pass
    if scope_filter.team_ids:
        team_uuids = [UUID(t) for t in scope_filter.team_ids if _is_uuid(t)]
        if team_uuids:
            args.append(team_uuids)
            conds.append(f"(scope_type = 'team' AND scope_id = ANY(${len(args)}::uuid[]))")
    if scope_filter.org_unit_paths:
        conds.append("scope_type = 'org_unit'")
    return f"({' OR '.join(conds)})" if conds else None


async def list_audit_events(
    conn: DbConn,
    *,
    organization_id: UUID,
    scope_filter: ScopeFilter,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    action: str | None = None,
    actor_member_id: UUID | None = None,
    from_time: datetime | None = None,
    to_time: datetime | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    if scope_filter.is_empty:
        return []
    clauses = ["organization_id = $1"]
    args: list[Any] = [organization_id]
    if not scope_filter.organization:
        cond = _build_scope_condition(scope_filter, args)
        if cond is None:
            return []
        clauses.append(cond)
    for col, val in [
        ("entity_type =", entity_type),
        ("entity_id =", entity_id),
        ("action =", action),
        ("actor_member_id =", actor_member_id),
        ("created_at >=", from_time),
        ("created_at <=", to_time),
    ]:
        if val is not None:
            args.append(val)
            clauses.append(f"{col} ${len(args)}")
    args.append(limit)
    sql = (  # nosec B608
        f"SELECT id, organization_id, actor_member_id, action, entity_type, entity_id, "  # nosec B608 # noqa: S608
        f"role_used, scope_type, scope_id, request_id, client_id, before_state, after_state, created_at "
        f"FROM public.audit_events WHERE {' AND '.join(clauses)} ORDER BY created_at DESC LIMIT ${len(args)}"
    )
    rows = await conn.fetch(sql, *args)
    return [
        {
            k: (json.loads(v) if k in ("before_state", "after_state") and isinstance(v, str) else v)
            for k, v in dict(r).items()
        }
        for r in rows
    ]


def _is_uuid(val: str) -> bool:
    try:
        UUID(val)
        return True
    except ValueError:
        return False
