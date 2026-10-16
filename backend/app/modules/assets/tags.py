# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Asset tag generation per organization (master M2.1-T3, §B7.3 `assets.tag`, §B8.1 Categories,
M1.3-T3 per-organization number sequences).

Every new asset gets a tag in the format of its organization's domain template (`assets.tag` in
`config/domains/*.yaml`, parsed into `TagConfig` by `app.modules.assets.config`), with a category's
`tag_prefix` overriding the template prefix when set (§B8.1). The numeric part comes from
`organization_sequences` (0018): one row per `(organization_id, sequence_key)`, counting from 1, so
each prefix has its own independent, gap-tolerant counter per organization (M1.3-T3). The sequence
key is `asset_tag:<prefix>`, never the bare prefix, so a future non-tag sequence sharing this table
cannot collide with one.

Two shapes of tag reach an asset:

* **Generated** (`assign_tag`): the organization's own sequence supplies the number; by
  construction it is always unique within the organization, and tags cannot collide across
  organizations because every sequence is itself scoped by `organization_id`.
* **Supplied** (`validate_supplied_tag`): an asset created from a reserved QR tag (P9, M2.2-T6) or
  an import row (P10) brings its own tag. It must still match the template's (or category's) format,
  and still be unique in the organization - checked here, enforced by the caller inside its own
  write transaction (the `uq_assets__organization_id_tag` constraint from P8-03 is the backstop).

Both `assign_tag` and `validate_supplied_tag` must run on a connection already inside the caller's
own write transaction (after `tenant_transaction`/`worker_context` opened it, per `db-conventions`),
so the row lock `next_tag` takes through `INSERT ... ON CONFLICT ... DO UPDATE` is held for the rest
of that same transaction - no other concurrent creator can observe or reuse the same number before
it commits or rolls back. Because the counter lives in this same transaction (not a standalone
PostgreSQL `SEQUENCE`, which never rolls back), a solo rolled-back create's number is simply
available again afterwards - no permanent gap - but it can never equal a number an earlier,
*committed* create already turned into a tag: only uniqueness is promised, not a contiguous
sequence or a reservation that survives a rollback.
"""

from __future__ import annotations

import re
from uuid import UUID

from app.core.db import Connection
from app.core.ids import uuid7
from app.modules.assets.config import TagConfig
from app.modules.assets.errors import TagConflictError, TagInvalidError

__all__ = [
    "assign_tag",
    "effective_prefix",
    "format_tag",
    "next_tag",
    "validate_supplied_tag",
]

_SELECT_TAG_CONFLICT = "SELECT 1 FROM public.assets WHERE organization_id = $1 AND tag = $2"

_NEXT_VALUE_SQL = """
INSERT INTO public.organization_sequences (id, organization_id, sequence_key, next_value)
VALUES ($1, $2, $3, 2)
ON CONFLICT (organization_id, sequence_key)
    DO UPDATE SET next_value = public.organization_sequences.next_value + 1
RETURNING next_value - 1
"""


def effective_prefix(tag_config: TagConfig, category_prefix: str | None) -> str:
    """The prefix to use: the category's override when set, otherwise the template's own (§B8.1)."""
    return category_prefix if category_prefix is not None else tag_config.prefix


def format_tag(tag_config: TagConfig, category_prefix: str | None, number: int) -> str:
    """Format `number` as a tag: prefix + separator + the number zero-padded to `digits` (pure).

    A number that outgrows `digits` keeps all of its digits rather than wrapping or truncating
    (`str.zfill` already does this: it only ever pads, never cuts).
    """
    prefix = effective_prefix(tag_config, category_prefix)
    padded = str(number).zfill(tag_config.digits)
    return f"{prefix}{tag_config.separator}{padded}"


def _tag_pattern(tag_config: TagConfig, category_prefix: str | None) -> re.Pattern[str]:
    prefix = effective_prefix(tag_config, category_prefix)
    return re.compile(rf"^{re.escape(prefix)}{re.escape(tag_config.separator)}\d{{{tag_config.digits},}}$")


def _sequence_key(prefix: str) -> str:
    return f"asset_tag:{prefix}"


async def next_tag(conn: Connection, organization_id: UUID, prefix: str) -> int:
    """Return the next number of this organization's counter for `prefix`, starting at 1.

    `prefix` is already resolved (the template's prefix, or a category's override): each distinct
    prefix counts on its own. The `INSERT ... ON CONFLICT ... DO UPDATE` is one atomic statement, so
    the first caller for a prefix creates the counter and the next caller increments it, with no
    separate existence check that a second concurrent caller could race past. `DO UPDATE` takes the
    row's lock for the statement, serializing concurrent callers; the lock is released when the
    enclosing transaction commits or rolls back, not before - so two concurrent creators in the
    same organization always receive two different numbers.
    """
    number: int = await conn.fetchval(_NEXT_VALUE_SQL, uuid7(), organization_id, _sequence_key(prefix))
    return number


async def assign_tag(
    conn: Connection,
    organization_id: UUID,
    tag_config: TagConfig,
    category_prefix: str | None = None,
) -> str:
    """Generate the next tag for a new asset: resolve the prefix, take the next number, format it."""
    prefix = effective_prefix(tag_config, category_prefix)
    number = await next_tag(conn, organization_id, prefix)
    return format_tag(tag_config, category_prefix, number)


async def validate_supplied_tag(
    conn: Connection,
    organization_id: UUID,
    tag_config: TagConfig,
    category_prefix: str | None,
    tag: str,
) -> None:
    """Refuse a caller-supplied tag that does not match the format, or clashes (§B7.3, §B8.1).

    Raises `TagInvalidError` (422 `asset.tag_invalid`) when `tag` does not match the organization's
    tag format (template prefix or category override, separator, at least `digits` digits).
    Raises `TagConflictError` (409 `asset.tag_conflict`) when another asset in the same organization
    already has this exact tag. Must run inside the caller's own write transaction, before the
    insert: the `uq_assets__organization_id_tag` constraint is the backstop if a race still slips
    through between this check and the insert.
    """
    if not _tag_pattern(tag_config, category_prefix).match(tag):
        prefix = effective_prefix(tag_config, category_prefix)
        raise TagInvalidError(
            f"tag must start with {prefix!r}{tag_config.separator!r} followed by at least "
            f"{tag_config.digits} digits"
        )
    conflict = await conn.fetchval(_SELECT_TAG_CONFLICT, organization_id, tag)
    if conflict:
        raise TagConflictError(f"tag {tag!r} is already used by another asset in this organization")
