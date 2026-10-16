# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Unique-in-organization custom fields (§B8.1 Custom fields rules).

A `custom_field_definitions` row may set `is_unique` (refused together with `is_encrypted`: an
encrypted value cannot be compared, so it can never be unique - enforced where the definition is
saved, P8-07). Checking it needs a write-transaction-scoped advisory lock so two concurrent writes
with the same value cannot both pass before either commits: `pg_advisory_xact_lock` on a hash of
`(organization_id, field key, value)` serializes the two checks, and the lock is released
automatically when the transaction ends (commit or rollback).

`lock_and_check_unique_custom_field` must run on the connection already inside the write's own
transaction (after `tenant_transaction`/`worker_context` opened it), before the row is written.
"""

from __future__ import annotations

import hashlib
import struct
from uuid import UUID

from app.core.db import Connection
from app.core.problems import FieldError
from app.modules.assets.errors import CustomFieldValidationError

__all__ = ["lock_and_check_unique_custom_field"]

_SELECT_CONFLICT = (
    "SELECT 1 FROM public.assets WHERE organization_id = $1 AND custom_fields ->> $2 = $3 AND id <> $4"
)


def _advisory_lock_key(organization_id: UUID, field_key: str, value: str) -> int:
    """A signed 64-bit key for `pg_advisory_xact_lock`, stable for the same (org, field, value)."""
    digest = hashlib.sha256(f"{organization_id}:{field_key}:{value}".encode()).digest()[:8]
    unsigned: int = struct.unpack(">Q", digest)[0]
    return unsigned - 2**64 if unsigned >= 2**63 else unsigned


async def lock_and_check_unique_custom_field(
    conn: Connection,
    *,
    organization_id: UUID,
    field_key: str,
    value: str,
    asset_id: UUID,
) -> None:
    """Take the transaction-scoped advisory lock, then refuse a value already used by another asset.

    Call once per unique field of a write, inside the same transaction as the insert/update.
    Raises `CustomFieldValidationError` (422 `asset.custom_field_invalid`) on a conflict.
    """
    lock_key = _advisory_lock_key(organization_id, field_key, value)
    await conn.execute("SELECT pg_advisory_xact_lock($1)", lock_key)
    conflict = await conn.fetchval(_SELECT_CONFLICT, organization_id, field_key, value, asset_id)
    if conflict:
        message = "this value is already used by another asset"
        raise CustomFieldValidationError([FieldError(field=f"custom_fields.{field_key}", message=message)])
