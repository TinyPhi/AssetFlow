# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Catalog reference-data repositories: raw SQL against the P8-02 tables (§C4.4, M2.1-T1/T2).

Every query is organization-scoped (`organization_id` first) and relies on RLS as the backstop
(§C1.4); list queries use keyset cursor pagination (§B4.5, §C1.5): `(code, id)` ascending for
categories and custom field definitions, `(name, id)` ascending for manufacturers and suppliers.
"""

from __future__ import annotations

import base64
import json
import re
from typing import Any
from uuid import UUID

import asyncpg

from app.core.permissions import ScopeFilter

type DbConn = asyncpg.Connection[asyncpg.Record] | asyncpg.pool.PoolConnectionProxy[asyncpg.Record]

__all__ = [
    "CategoryRepository",
    "CustomFieldDefinitionRepository",
    "ManufacturerRepository",
    "ReferenceDataRepository",
    "SupplierRepository",
    "decode_cursor",
    "decode_field_cursor",
    "encode_cursor",
    "encode_field_cursor",
    "to_ltree_label",
]


def to_ltree_label(code: str) -> str:
    """Convert a business code into a valid PostgreSQL ltree label (same pattern as org_units, P5-04).

    Not imported from `app.modules.organization.repository`: that module is private to the
    organization module (`.importlinter` `repo-organization` contract); this is a small, pure
    duplicate rather than a cross-module repository import.
    """
    label = re.sub(r"[^a-zA-Z0-9_]", "_", code.strip().lower())
    if not label:
        raise ValueError("code produces an empty ltree label")
    return label


def encode_cursor(value: str, record_id: UUID) -> str:
    """Opaque keyset cursor: the last row's own sort key (§B4.5)."""
    raw = json.dumps([value, str(record_id)]).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(cursor: str) -> tuple[str, UUID]:
    """Inverse of `encode_cursor`; raises `ValueError`/`KeyError` on anything malformed."""
    raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
    value, id_raw = json.loads(raw)
    return str(value), UUID(id_raw)


def encode_field_cursor(position: int, key: str, record_id: UUID) -> str:
    """Opaque keyset cursor for custom-field definitions, sorted `(position, key, id)`.

    A plain `(key, id)` cursor (as `encode_cursor` gives categories/manufacturers/suppliers, all
    sorted by a single text column then id) silently drops rows here: two fields can share a key
    prefix but sort at different positions, so the cursor must carry all three sort columns.
    """
    raw = json.dumps([position, key, str(record_id)]).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_field_cursor(cursor: str) -> tuple[int, str, UUID]:
    """Inverse of `encode_field_cursor`; raises `ValueError`/`KeyError`/`TypeError` on malformed input."""
    raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
    position, key, id_raw = json.loads(raw)
    if not isinstance(position, int):
        raise TypeError("cursor position must be an integer")
    return position, str(key), UUID(id_raw)


_CATEGORY_COLUMNS = (
    "id, organization_id, parent_id, path::text AS path, code, name, tag_prefix, "
    "default_criticality, responsible_team_id, status, version, created_at, updated_at"
)


class CategoryRepository:
    """Asset categories: a tree via ltree materialized path (same shape as org_units)."""

    async def get_by_id(
        self, conn: DbConn, *, organization_id: UUID, category_id: UUID, for_update: bool = False
    ) -> asyncpg.Record | None:
        lock = " FOR UPDATE" if for_update else ""
        sql = (
            f"SELECT {_CATEGORY_COLUMNS} FROM public.asset_categories "  # nosec B608  # noqa: S608
            f"WHERE organization_id = $1 AND id = $2{lock}"
        )
        return await conn.fetchrow(sql, organization_id, category_id)

    async def get_by_code(
        self, conn: DbConn, *, organization_id: UUID, code: str, for_update: bool = False
    ) -> asyncpg.Record | None:
        lock = " FOR UPDATE" if for_update else ""
        sql = (
            f"SELECT {_CATEGORY_COLUMNS} FROM public.asset_categories "  # nosec B608  # noqa: S608
            f"WHERE organization_id = $1 AND code = $2{lock}"
        )
        return await conn.fetchrow(sql, organization_id, code)

    async def create(
        self,
        conn: DbConn,
        *,
        category_id: UUID,
        organization_id: UUID,
        parent_id: UUID | None,
        path: str,
        code: str,
        name: str,
        tag_prefix: str | None,
        default_criticality: str | None,
        responsible_team_id: UUID | None,
    ) -> asyncpg.Record:
        return await conn.fetchrow(  # type: ignore[return-value]
            "INSERT INTO public.asset_categories "  # nosec B608  # noqa: S608
            "(id, organization_id, parent_id, path, code, name, tag_prefix, default_criticality, "
            "responsible_team_id, status, version) "
            "VALUES ($1, $2, $3, $4::ltree, $5, $6, $7, $8, $9, 'active', 1) "
            f"RETURNING {_CATEGORY_COLUMNS}",
            category_id,
            organization_id,
            parent_id,
            path,
            code,
            name,
            tag_prefix,
            default_criticality,
            responsible_team_id,
        )

    async def update(
        self,
        conn: DbConn,
        *,
        organization_id: UUID,
        category_id: UUID,
        version: int,
        name: str | None = None,
        tag_prefix: str | None = None,
        clear_tag_prefix: bool = False,
        default_criticality: str | None = None,
        clear_default_criticality: bool = False,
        responsible_team_id: UUID | None = None,
        clear_responsible_team: bool = False,
    ) -> asyncpg.Record | None:
        sets = ["version = version + 1", "updated_at = now()"]
        args: list[Any] = [organization_id, category_id, version]

        if name is not None:
            args.append(name)
            sets.append(f"name = ${len(args)}")
        if clear_tag_prefix:
            sets.append("tag_prefix = NULL")
        elif tag_prefix is not None:
            args.append(tag_prefix)
            sets.append(f"tag_prefix = ${len(args)}")
        if clear_default_criticality:
            sets.append("default_criticality = NULL")
        elif default_criticality is not None:
            args.append(default_criticality)
            sets.append(f"default_criticality = ${len(args)}")
        if clear_responsible_team:
            sets.append("responsible_team_id = NULL")
        elif responsible_team_id is not None:
            args.append(responsible_team_id)
            sets.append(f"responsible_team_id = ${len(args)}")

        sql = (
            f"UPDATE public.asset_categories SET {', '.join(sets)} "  # nosec B608  # noqa: S608
            f"WHERE organization_id = $1 AND id = $2 AND version = $3 "
            f"RETURNING {_CATEGORY_COLUMNS}"
        )
        return await conn.fetchrow(sql, *args)

    async def move(
        self,
        conn: DbConn,
        *,
        organization_id: UUID,
        category_id: UUID,
        version: int,
        new_parent_id: UUID,
        old_path: str,
        new_path: str,
    ) -> asyncpg.Record | None:
        """Move a node and cascade path updates to all descendants in one transaction."""
        await conn.execute(
            "UPDATE public.asset_categories "
            "SET path = $1::ltree || subpath(path, nlevel($2::ltree)), updated_at = now() "
            "WHERE organization_id = $3 AND path <@ $2::ltree AND id != $4",
            new_path,
            old_path,
            organization_id,
            category_id,
        )
        sql = (
            "UPDATE public.asset_categories "  # nosec B608  # noqa: S608
            "SET parent_id = $1, path = $2::ltree, version = version + 1, updated_at = now() "
            "WHERE organization_id = $3 AND id = $4 AND version = $5 "
            f"RETURNING {_CATEGORY_COLUMNS}"
        )
        return await conn.fetchrow(sql, new_parent_id, new_path, organization_id, category_id, version)

    async def archive(
        self, conn: DbConn, *, organization_id: UUID, category_id: UUID, version: int
    ) -> asyncpg.Record | None:
        sql = (
            "UPDATE public.asset_categories "  # nosec B608  # noqa: S608
            "SET status = 'archived', version = version + 1, updated_at = now() "
            "WHERE organization_id = $1 AND id = $2 AND version = $3 "
            f"RETURNING {_CATEGORY_COLUMNS}"
        )
        return await conn.fetchrow(sql, organization_id, category_id, version)

    async def lock_active_children(
        self, conn: DbConn, *, organization_id: UUID, category_id: UUID
    ) -> list[UUID]:
        """Active children, locked for the caller's transaction (archive-TOCTOU guard, §C4.4).

        A plain `count(*)` lets a concurrent `create_category` (new child under this parent) or
        `assign_category` (asset moved onto this category) land between the count and the archive
        UPDATE, producing an archived category with live children/assets. Locking the rows that
        exist right now forces a concurrent UPDATE of one of them to wait for this transaction;
        `SKIP LOCKED` means a row already locked by an unrelated concurrent write is left out of
        the count rather than blocking this one (accepted trade-off, same one the review proposed).
        """
        rows = await conn.fetch(
            "SELECT id FROM public.asset_categories "
            "WHERE organization_id = $1 AND parent_id = $2 AND status = 'active' "
            "FOR UPDATE SKIP LOCKED",
            organization_id,
            category_id,
        )
        return [r["id"] for r in rows]

    async def lock_assets_using(
        self, conn: DbConn, *, organization_id: UUID, category_id: UUID
    ) -> list[UUID]:
        """Assets currently on this category, locked for the caller's transaction (see above)."""
        rows = await conn.fetch(
            "SELECT id FROM public.assets WHERE organization_id = $1 AND category_id = $2 "
            "FOR UPDATE SKIP LOCKED",
            organization_id,
            category_id,
        )
        return [r["id"] for r in rows]

    async def list_page(
        self,
        conn: DbConn,
        *,
        organization_id: UUID,
        scope_filter: ScopeFilter,
        status: str | None = None,
        parent_id: UUID | None = None,
        after: tuple[str, UUID] | None = None,
        limit: int = 50,
    ) -> list[asyncpg.Record]:
        """Categories are organization-wide reference data: `scope_filter` must already be
        `ScopeFilter.all_organization()` (the service checked the permission before building it,
        §B7.1); kept as an explicit argument per the module's "no list without a ScopeFilter" rule
        rather than silently ignored.
        """
        if not scope_filter.organization:
            raise ValueError(
                "asset categories are organization-wide; scope_filter must cover the whole organization"
            )
        clauses = ["organization_id = $1"]
        args: list[Any] = [organization_id]
        if status is not None:
            args.append(status)
            clauses.append(f"status = ${len(args)}")
        if parent_id is not None:
            args.append(parent_id)
            clauses.append(f"parent_id = ${len(args)}")
        if after is not None:
            after_code, after_id = after
            args.extend([after_code, after_id])
            clauses.append(f"(code, id) > (${len(args) - 1}, ${len(args)})")
        args.append(limit)
        sql = (
            f"SELECT {_CATEGORY_COLUMNS} FROM public.asset_categories "  # nosec B608  # noqa: S608
            f"WHERE {' AND '.join(clauses)} ORDER BY code ASC, id ASC LIMIT ${len(args)}"
        )
        return await conn.fetch(sql, *args)


_FIELD_COLUMNS = (
    "id, organization_id, category_id, key, label, field_type, is_required, rules, "
    "is_unique, is_encrypted, position, status, version, created_at, updated_at"
)


class CustomFieldDefinitionRepository:
    """Per-category custom field declarations (§B8.1)."""

    async def get_by_id(
        self, conn: DbConn, *, organization_id: UUID, field_id: UUID, for_update: bool = False
    ) -> asyncpg.Record | None:
        lock = " FOR UPDATE" if for_update else ""
        sql = (
            f"SELECT {_FIELD_COLUMNS} FROM public.custom_field_definitions "  # nosec B608  # noqa: S608
            f"WHERE organization_id = $1 AND id = $2{lock}"
        )
        return await conn.fetchrow(sql, organization_id, field_id)

    async def get_by_key(
        self, conn: DbConn, *, organization_id: UUID, category_id: UUID, key: str, for_update: bool = False
    ) -> asyncpg.Record | None:
        lock = " FOR UPDATE" if for_update else ""
        sql = (
            f"SELECT {_FIELD_COLUMNS} FROM public.custom_field_definitions "  # nosec B608  # noqa: S608
            f"WHERE organization_id = $1 AND category_id = $2 AND key = $3{lock}"
        )
        return await conn.fetchrow(sql, organization_id, category_id, key)

    async def create(
        self,
        conn: DbConn,
        *,
        field_id: UUID,
        organization_id: UUID,
        category_id: UUID,
        key: str,
        label: str,
        field_type: str,
        is_required: bool,
        rules: dict[str, object],
        is_unique: bool,
        is_encrypted: bool,
        position: int,
    ) -> asyncpg.Record:
        return await conn.fetchrow(  # type: ignore[return-value]
            "INSERT INTO public.custom_field_definitions "  # nosec B608  # noqa: S608
            "(id, organization_id, category_id, key, label, field_type, is_required, rules, "
            "is_unique, is_encrypted, position, status, version) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10, $11, 'active', 1) "
            f"RETURNING {_FIELD_COLUMNS}",
            field_id,
            organization_id,
            category_id,
            key,
            label,
            field_type,
            is_required,
            json.dumps(rules),
            is_unique,
            is_encrypted,
            position,
        )

    async def update(
        self,
        conn: DbConn,
        *,
        organization_id: UUID,
        field_id: UUID,
        version: int,
        label: str | None = None,
        field_type: str | None = None,
        is_required: bool | None = None,
        rules: dict[str, object] | None = None,
        is_unique: bool | None = None,
        position: int | None = None,
    ) -> asyncpg.Record | None:
        sets = ["version = version + 1", "updated_at = now()"]
        args: list[Any] = [organization_id, field_id, version]

        if label is not None:
            args.append(label)
            sets.append(f"label = ${len(args)}")
        if field_type is not None:
            args.append(field_type)
            sets.append(f"field_type = ${len(args)}")
        if is_required is not None:
            args.append(is_required)
            sets.append(f"is_required = ${len(args)}")
        if rules is not None:
            args.append(json.dumps(rules))
            sets.append(f"rules = ${len(args)}::jsonb")
        if is_unique is not None:
            args.append(is_unique)
            sets.append(f"is_unique = ${len(args)}")
        if position is not None:
            args.append(position)
            sets.append(f"position = ${len(args)}")

        sql = (
            f"UPDATE public.custom_field_definitions SET {', '.join(sets)} "  # nosec B608  # noqa: S608
            f"WHERE organization_id = $1 AND id = $2 AND version = $3 "
            f"RETURNING {_FIELD_COLUMNS}"
        )
        return await conn.fetchrow(sql, *args)

    async def archive(
        self, conn: DbConn, *, organization_id: UUID, field_id: UUID, version: int
    ) -> asyncpg.Record | None:
        sql = (
            "UPDATE public.custom_field_definitions "  # nosec B608  # noqa: S608
            "SET status = 'archived', version = version + 1, updated_at = now() "
            "WHERE organization_id = $1 AND id = $2 AND version = $3 "
            f"RETURNING {_FIELD_COLUMNS}"
        )
        return await conn.fetchrow(sql, organization_id, field_id, version)

    async def count_assets_with_value(self, conn: DbConn, *, organization_id: UUID, key: str) -> int:
        """Any asset in the organization already storing a value (plain or encrypted) for `key`."""
        val: int | None = await conn.fetchval(
            "SELECT count(*) FROM public.assets "
            "WHERE organization_id = $1 AND (custom_fields ? $2 OR encrypted_fields ? $2)",
            organization_id,
            key,
        )
        return val or 0

    async def list_by_category(
        self,
        conn: DbConn,
        *,
        organization_id: UUID,
        scope_filter: ScopeFilter,
        category_id: UUID,
        status: str | None = None,
        after: tuple[int, str, UUID] | None = None,
        limit: int = 50,
    ) -> list[asyncpg.Record]:
        """Organization-wide reference data; see `CategoryRepository.list_page`."""
        if not scope_filter.organization:
            raise ValueError(
                "custom field definitions are organization-wide; scope_filter must cover the whole "
                "organization"
            )
        clauses = ["organization_id = $1", "category_id = $2"]
        args: list[Any] = [organization_id, category_id]
        if status is not None:
            args.append(status)
            clauses.append(f"status = ${len(args)}")
        if after is not None:
            # Must match the query's own sort key exactly: (position, key, id), not just (key, id),
            # or rows with the same key prefix but a different position silently drop on later pages.
            after_position, after_key, after_id = after
            args.extend([after_position, after_key, after_id])
            clauses.append(f"(position, key, id) > (${len(args) - 2}, ${len(args) - 1}, ${len(args)})")
        args.append(limit)
        sql = (
            f"SELECT {_FIELD_COLUMNS} FROM public.custom_field_definitions "  # nosec B608  # noqa: S608
            f"WHERE {' AND '.join(clauses)} ORDER BY position ASC, key ASC, id ASC LIMIT ${len(args)}"
        )
        return await conn.fetch(sql, *args)


_REFERENCE_COLUMNS = (
    "id, organization_id, code, name, contact, notes, status, version, created_at, updated_at"
)


class ReferenceDataRepository:
    """Shared implementation for manufacturers and suppliers (identical shape, §B8.1)."""

    _table: str = ""
    _columns: str = _REFERENCE_COLUMNS

    async def get_by_id(
        self, conn: DbConn, *, organization_id: UUID, record_id: UUID, for_update: bool = False
    ) -> asyncpg.Record | None:
        lock = " FOR UPDATE" if for_update else ""
        sql = (
            f"SELECT {self._columns} FROM public.{self._table} "  # nosec B608  # noqa: S608
            f"WHERE organization_id = $1 AND id = $2{lock}"
        )
        return await conn.fetchrow(sql, organization_id, record_id)

    async def get_by_name(
        self, conn: DbConn, *, organization_id: UUID, name: str, for_update: bool = False
    ) -> asyncpg.Record | None:
        lock = " FOR UPDATE" if for_update else ""
        sql = (
            f"SELECT {self._columns} FROM public.{self._table} "  # nosec B608  # noqa: S608
            f"WHERE organization_id = $1 AND name = $2{lock}"
        )
        return await conn.fetchrow(sql, organization_id, name)

    async def create(
        self,
        conn: DbConn,
        *,
        record_id: UUID,
        organization_id: UUID,
        code: str | None,
        name: str,
        contact: dict[str, object],
        notes: str | None,
    ) -> asyncpg.Record:
        sql = (
            f"INSERT INTO public.{self._table} "  # nosec B608  # noqa: S608
            "(id, organization_id, code, name, contact, notes, status, version) "
            "VALUES ($1, $2, $3, $4, $5::jsonb, $6, 'active', 1) "
            f"RETURNING {self._columns}"
        )
        return await conn.fetchrow(  # type: ignore[return-value]
            sql, record_id, organization_id, code, name, json.dumps(contact), notes
        )

    async def update(
        self,
        conn: DbConn,
        *,
        organization_id: UUID,
        record_id: UUID,
        version: int,
        name: str | None = None,
        contact: dict[str, object] | None = None,
        notes: str | None = None,
        clear_notes: bool = False,
    ) -> asyncpg.Record | None:
        sets = ["version = version + 1", "updated_at = now()"]
        args: list[Any] = [organization_id, record_id, version]

        if name is not None:
            args.append(name)
            sets.append(f"name = ${len(args)}")
        if contact is not None:
            args.append(json.dumps(contact))
            sets.append(f"contact = ${len(args)}::jsonb")
        if clear_notes:
            sets.append("notes = NULL")
        elif notes is not None:
            args.append(notes)
            sets.append(f"notes = ${len(args)}")

        sql = (
            f"UPDATE public.{self._table} SET {', '.join(sets)} "  # nosec B608  # noqa: S608
            f"WHERE organization_id = $1 AND id = $2 AND version = $3 "
            f"RETURNING {self._columns}"
        )
        return await conn.fetchrow(sql, *args)

    async def archive(
        self, conn: DbConn, *, organization_id: UUID, record_id: UUID, version: int
    ) -> asyncpg.Record | None:
        sql = (
            f"UPDATE public.{self._table} "  # nosec B608  # noqa: S608
            "SET status = 'archived', version = version + 1, updated_at = now() "
            "WHERE organization_id = $1 AND id = $2 AND version = $3 "
            f"RETURNING {self._columns}"
        )
        return await conn.fetchrow(sql, organization_id, record_id, version)

    async def list_page(
        self,
        conn: DbConn,
        *,
        organization_id: UUID,
        scope_filter: ScopeFilter,
        status: str | None = None,
        after: tuple[str, UUID] | None = None,
        limit: int = 50,
    ) -> list[asyncpg.Record]:
        """Organization-wide reference data; see `CategoryRepository.list_page`."""
        if not scope_filter.organization:
            raise ValueError(
                f"{self._table} are organization-wide; scope_filter must cover the whole organization"
            )
        clauses = ["organization_id = $1"]
        args: list[Any] = [organization_id]
        if status is not None:
            args.append(status)
            clauses.append(f"status = ${len(args)}")
        if after is not None:
            after_name, after_id = after
            args.extend([after_name, after_id])
            clauses.append(f"(name, id) > (${len(args) - 1}, ${len(args)})")
        args.append(limit)
        sql = (
            f"SELECT {self._columns} FROM public.{self._table} "  # nosec B608  # noqa: S608
            f"WHERE {' AND '.join(clauses)} ORDER BY name ASC, id ASC LIMIT ${len(args)}"
        )
        return await conn.fetch(sql, *args)


class ManufacturerRepository(ReferenceDataRepository):
    _table = "manufacturers"


class SupplierRepository(ReferenceDataRepository):
    _table = "suppliers"
