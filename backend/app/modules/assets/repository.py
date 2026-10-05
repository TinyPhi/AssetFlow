# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Asset repository: raw SQL against `public.assets` and its reference joins (§C4.4, M2.1-T5, P8-07).

Reads duplicate `v_asset_inventory`'s own join shape (P8-03) rather than querying the view directly:
the view's `holder_id` is `COALESCE(holder_member_id, holder_team_id, holder_location_id)`, which
is not a plain column reference, so a predicate on it can never use the `ix_assets__…_holder_*`
indexes the scope filter needs (§B5.3, the plan's own "EXPLAIN proves index use" requirement). This
module keeps the same joins so the response shape matches, but filters directly on `assets`' own
columns so the planner can still choose an index.

List queries build the id set as a `UNION` of the three scope branches (org-unit-path, team, self),
same pattern as `app.modules.organization.repository.OrgUnitRepository.list` (§B5.3); organization
scope skips the branch filter entirely. Cursor pagination (§B4.5) is keyset-based: `(sort_key, id)`
for the default columns, or `(search_rank, id)` while a free-text `q` ranks the page.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import asyncpg

from app.core.permissions import ScopeFilter

type DbConn = asyncpg.Connection[asyncpg.Record] | asyncpg.pool.PoolConnectionProxy[asyncpg.Record]

__all__ = [
    "SORT_COLUMNS",
    "AssetQuery",
    "AssetRepository",
    "decode_cursor",
    "encode_cursor",
]


def encode_cursor(value: str, record_id: UUID) -> str:
    raw = json.dumps([value, str(record_id)]).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(cursor: str) -> tuple[str, UUID]:
    raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
    value, id_raw = json.loads(raw)
    return str(value), UUID(id_raw)


#: Allowlisted sort columns (§C4.4: never build ORDER BY from raw user input); `-` prefix descends.
SORT_COLUMNS: dict[str, str] = {
    "tag": "a.tag",
    "name": "a.name",
    "status": "a.status",
    "created_at": "a.created_at",
    "updated_at": "a.updated_at",
    "warranty_end": "a.warranty_end",
    "purchase_date": "a.purchase_date",
}

#: Nullable sort columns always sort their NULLs last, regardless of direction, by substituting a
#: sentinel for the comparison (both ORDER BY and the keyset predicate use the same expression, so
#: three-valued NULL logic never enters the row comparison - see repository docstring).
_NULLABLE_SENTINELS: dict[str, tuple[str, str]] = {
    "warranty_end": ("9999-12-31", "0001-01-01"),
    "purchase_date": ("9999-12-31", "0001-01-01"),
}

_CAST_BY_COLUMN: dict[str, str] = {
    "created_at": "::timestamptz",
    "updated_at": "::timestamptz",
    "warranty_end": "::date",
    "purchase_date": "::date",
}

_BASE_COLUMNS = """
    a.id, a.organization_id, a.tag, a.name, a.category_id, cat.name AS category_name,
    a.model, a.manufacturer_id, mfr.name AS manufacturer_name,
    a.supplier_id, sup.name AS supplier_name, a.serial_number,
    a.owner_org_unit_id, ou.name AS owner_org_unit_name, a.owner_org_unit_path::text AS owner_org_unit_path,
    a.location_id, loc.name AS location_name,
    CASE
        WHEN a.holder_member_id IS NOT NULL THEN 'member'
        WHEN a.holder_team_id IS NOT NULL THEN 'team'
        WHEN a.holder_location_id IS NOT NULL THEN 'location'
        ELSE NULL
    END AS holder_type,
    COALESCE(a.holder_member_id, a.holder_team_id, a.holder_location_id) AS holder_id,
    COALESCE(hm.display_name, ht.name, hl.name) AS holder_display_name,
    a.status, a.criticality, a.purchase_date, a.purchase_cost, a.warranty_end,
    a.custom_fields, a.encrypted_fields, a.notes, a.version, a.created_at, a.updated_at
"""

_JOINS = """
    FROM public.assets a
    JOIN public.asset_categories cat ON cat.organization_id = a.organization_id AND cat.id = a.category_id
    LEFT JOIN public.manufacturers mfr
        ON mfr.organization_id = a.organization_id AND mfr.id = a.manufacturer_id
    LEFT JOIN public.suppliers sup ON sup.organization_id = a.organization_id AND sup.id = a.supplier_id
    JOIN public.org_units ou ON ou.organization_id = a.organization_id AND ou.id = a.owner_org_unit_id
    LEFT JOIN public.locations loc ON loc.organization_id = a.organization_id AND loc.id = a.location_id
    LEFT JOIN public.members hm ON hm.organization_id = a.organization_id AND hm.id = a.holder_member_id
    LEFT JOIN public.teams ht ON ht.organization_id = a.organization_id AND ht.id = a.holder_team_id
    LEFT JOIN public.locations hl ON hl.organization_id = a.organization_id AND hl.id = a.holder_location_id
"""

_ASSET_COLUMNS = (
    "id, organization_id, tag, name, category_id, model, manufacturer_id, supplier_id, "
    "serial_number, owner_org_unit_id, owner_org_unit_path::text AS owner_org_unit_path, location_id, "
    "holder_member_id, holder_team_id, holder_location_id, status, criticality, purchase_date, "
    "purchase_cost, warranty_end, custom_fields, encrypted_fields, notes, idempotency_key, "
    "version, created_at, updated_at"
)


@dataclass(frozen=True)
class AssetQuery:
    """Every list filter (§B8.1, §B5.3); `None`/`()` means "no filter" for that field."""

    q: str | None = None
    status: tuple[str, ...] = ()
    category_id: UUID | None = None
    include_subcategories: bool = False
    owner_org_unit_id: UUID | None = None
    include_sub_units: bool = False
    location_id: UUID | None = None
    include_sub_locations: bool = False
    holder_type: str | None = None
    holder_member_id: UUID | None = None
    holder_team_id: UUID | None = None
    criticality: tuple[str, ...] = ()
    manufacturer_id: UUID | None = None
    supplier_id: UUID | None = None
    warranty_end_before: str | None = None
    warranty_end_after: str | None = None
    purchase_date_before: str | None = None
    purchase_date_after: str | None = None
    updated_since: str | None = None
    custom_field_filters: tuple[tuple[str, str, str], ...] = ()  # (key, op, value)


class AssetRepository:
    async def get_by_id(
        self, conn: DbConn, *, organization_id: UUID, asset_id: UUID, for_update: bool = False
    ) -> asyncpg.Record | None:
        lock = " FOR UPDATE" if for_update else ""
        sql = (
            f"SELECT {_ASSET_COLUMNS} FROM public.assets "  # noqa: S608
            f"WHERE organization_id = $1 AND id = $2{lock}"
        )
        return await conn.fetchrow(sql, organization_id, asset_id)

    async def get_by_tag(self, conn: DbConn, *, organization_id: UUID, tag: str) -> asyncpg.Record | None:
        return await conn.fetchrow(
            f"SELECT {_ASSET_COLUMNS} FROM public.assets WHERE organization_id = $1 AND tag = $2",  # noqa: S608
            organization_id,
            tag,
        )

    async def get_by_idempotency_key(
        self, conn: DbConn, *, organization_id: UUID, idempotency_key: str
    ) -> asyncpg.Record | None:
        return await conn.fetchrow(
            f"SELECT {_ASSET_COLUMNS} FROM public.assets "  # noqa: S608
            "WHERE organization_id = $1 AND idempotency_key = $2",
            organization_id,
            idempotency_key,
        )

    async def get_detail(
        self, conn: DbConn, *, organization_id: UUID, asset_id: UUID
    ) -> asyncpg.Record | None:
        sql = f"SELECT {_BASE_COLUMNS}{_JOINS}WHERE a.organization_id = $1 AND a.id = $2"
        return await conn.fetchrow(sql, organization_id, asset_id)

    async def create(
        self,
        conn: DbConn,
        *,
        asset_id: UUID,
        organization_id: UUID,
        tag: str,
        name: str,
        category_id: UUID,
        model: str | None,
        manufacturer_id: UUID | None,
        supplier_id: UUID | None,
        serial_number: str | None,
        owner_org_unit_id: UUID,
        location_id: UUID | None,
        status: str,
        criticality: str | None,
        purchase_date: Any,
        purchase_cost: Any,
        warranty_end: Any,
        custom_fields: Mapping[str, object],
        encrypted_fields: Mapping[str, str],
        notes: str | None,
        idempotency_key: str | None,
    ) -> asyncpg.Record:
        row = await conn.fetchrow(
            "INSERT INTO public.assets "  # noqa: S608
            "(id, organization_id, tag, name, category_id, model, manufacturer_id, supplier_id, "
            "serial_number, owner_org_unit_id, location_id, status, criticality, purchase_date, "
            "purchase_cost, warranty_end, custom_fields, encrypted_fields, notes, idempotency_key, version) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, "
            "$17::jsonb, $18::jsonb, $19, $20, 1) "
            f"RETURNING {_ASSET_COLUMNS}",
            asset_id,
            organization_id,
            tag,
            name,
            category_id,
            model,
            manufacturer_id,
            supplier_id,
            serial_number,
            owner_org_unit_id,
            location_id,
            status,
            criticality,
            purchase_date,
            purchase_cost,
            warranty_end,
            json.dumps(custom_fields),
            json.dumps(encrypted_fields),
            notes,
            idempotency_key,
        )
        assert row is not None  # noqa: S101 - INSERT ... RETURNING always returns exactly one row
        return row

    async def update(
        self,
        conn: DbConn,
        *,
        organization_id: UUID,
        asset_id: UUID,
        version: int,
        sets: dict[str, Any],
    ) -> asyncpg.Record | None:
        """`sets` is a pre-built `{column: value}` map (already-validated keys only, §C4.4)."""
        clauses = ["version = version + 1", "updated_at = now()"]
        args: list[Any] = [organization_id, asset_id, version]
        for column, value in sets.items():
            args.append(value)
            cast = "::jsonb" if column in ("custom_fields", "encrypted_fields") else ""
            clauses.append(f"{column} = ${len(args)}{cast}")
        sql = (
            f"UPDATE public.assets SET {', '.join(clauses)} "  # noqa: S608
            f"WHERE organization_id = $1 AND id = $2 AND version = $3 "
            f"RETURNING {_ASSET_COLUMNS}"
        )
        return await conn.fetchrow(sql, *args)

    async def departed_member_ids(
        self, conn: DbConn, *, organization_id: UUID, member_ids: list[UUID]
    ) -> set[UUID]:
        """One batched query per page (§B8.1 holder display): members who have left."""
        if not member_ids:
            return set()
        rows = await conn.fetch(
            "SELECT id FROM public.members WHERE organization_id = $1 AND id = ANY($2::uuid[]) "
            "AND status = 'left'",
            organization_id,
            member_ids,
        )
        return {r["id"] for r in rows}

    # ==========================================================================
    # List
    # ==========================================================================

    def _scope_branches(self, *, scope_filter: ScopeFilter, args: list[Any]) -> str | None:
        """Returns `None` for organization-wide scope (no restriction needed); else a `UNION` of
        `SELECT id FROM public.assets WHERE …` branches, one per covered scope kind (§B5.3)."""
        if scope_filter.organization:
            return None
        branches: list[str] = []
        if scope_filter.org_unit_paths:
            args.append(list(scope_filter.org_unit_paths))
            branches.append(
                "SELECT id FROM public.assets "  # noqa: S608
                f"WHERE organization_id = $1 AND owner_org_unit_path <@ ANY(${len(args)}::ltree[])"
            )
        team_uuids = [t for t in (_try_uuid(v) for v in scope_filter.team_ids) if t is not None]
        if team_uuids:
            args.append(team_uuids)
            branches.append(
                "SELECT id FROM public.assets "  # noqa: S608
                f"WHERE organization_id = $1 AND holder_team_id = ANY(${len(args)}::uuid[])"
            )
        member_uuid = _try_uuid(scope_filter.member_id) if scope_filter.member_id else None
        if member_uuid is not None:
            args.append(member_uuid)
            branches.append(
                "SELECT id FROM public.assets "  # noqa: S608
                f"WHERE organization_id = $1 AND holder_member_id = ${len(args)}"
            )
        if not branches:
            return "SELECT id FROM public.assets WHERE false"
        return " UNION ".join(branches)

    def _search_rank_expr(self, *, q: str, args: list[Any]) -> tuple[str, str]:
        """Returns `(predicate, rank_expr)` for a free-text search term (§B8.1 fuzzy search).

        3+ characters: `pg_trgm` similarity (`%`) over tag/name/serial_number/model, ranked by the
        best of the four similarities. Shorter input: prefix `ILIKE` (too short for trigram
        similarity to be meaningful), ranked by which field matched (tag first).
        """
        args.append(q)
        n = len(args)
        if len(q) >= 3:
            predicate = f"(a.tag % ${n} OR a.name % ${n} OR a.serial_number % ${n} OR a.model % ${n})"
            rank = (
                f"GREATEST(similarity(a.tag, ${n}), similarity(a.name, ${n}), "
                f"similarity(coalesce(a.serial_number, ''), ${n}), "
                f"similarity(coalesce(a.model, ''), ${n}))"
            )
        else:
            args.append(f"{q}%")
            like_n = len(args)
            predicate = (
                f"(a.tag ILIKE ${like_n} OR a.name ILIKE ${like_n} "
                f"OR a.serial_number ILIKE ${like_n} OR a.model ILIKE ${like_n})"
            )
            rank = (
                f"CASE WHEN a.tag ILIKE ${like_n} THEN 3 WHEN a.name ILIKE ${like_n} THEN 2 "
                f"WHEN a.serial_number ILIKE ${like_n} THEN 1 ELSE 0 END"
            )
        return predicate, rank

    def _custom_field_clause(self, key: str, op: str, value: str, args: list[Any]) -> str:
        column = f"a.custom_fields ->> '{key}'"
        if op == "eq":
            args.append(value)
            return f"{column} = ${len(args)}"
        if op == "gte":
            args.append(value)
            return (
                f"({column})::numeric >= ${len(args)}::numeric"
                if _is_number(value)
                else (f"{column} >= ${len(args)}")
            )
        if op == "lte":
            args.append(value)
            return (
                f"({column})::numeric <= ${len(args)}::numeric"
                if _is_number(value)
                else (f"{column} <= ${len(args)}")
            )
        raise ValueError(f"unsupported custom field operator {op!r}")

    async def list_assets(  # noqa: PLR0912, PLR0915
        self,
        conn: DbConn,
        *,
        organization_id: UUID,
        scope_filter: ScopeFilter,
        query: AssetQuery,
        sort: str = "-created_at",
        after: str | None = None,
        limit: int = 50,
        include_total: bool = False,
    ) -> tuple[list[asyncpg.Record], int | None]:
        args: list[Any] = [organization_id]
        where: list[str] = ["a.organization_id = $1"]

        scope_sql = self._scope_branches(scope_filter=scope_filter, args=args)
        if scope_sql is not None:
            where.append(f"a.id IN ({scope_sql})")

        search_rank: str | None = None
        if query.q:
            predicate, rank = self._search_rank_expr(q=query.q, args=args)
            where.append(predicate)
            search_rank = rank

        if query.status:
            args.append(list(query.status))
            where.append(f"a.status = ANY(${len(args)}::text[])")
        if query.category_id is not None:
            if query.include_subcategories:
                args.append(query.category_id)
                n = len(args)
                where.append(
                    "a.category_id IN (SELECT id FROM public.asset_categories "  # noqa: S608
                    f"WHERE organization_id = $1 AND (id = ${n} OR path <@ "
                    f"(SELECT path FROM public.asset_categories WHERE organization_id = $1 AND id = ${n})))"
                )
            else:
                args.append(query.category_id)
                where.append(f"a.category_id = ${len(args)}")
        if query.owner_org_unit_id is not None:
            if query.include_sub_units:
                args.append(query.owner_org_unit_id)
                where.append(
                    "a.owner_org_unit_path <@ (SELECT path FROM public.org_units "  # noqa: S608
                    f"WHERE organization_id = $1 AND id = ${len(args)})"
                )
            else:
                args.append(query.owner_org_unit_id)
                where.append(f"a.owner_org_unit_id = ${len(args)}")
        if query.location_id is not None:
            if query.include_sub_locations:
                args.append(query.location_id)
                n = len(args)
                where.append(
                    "a.location_id IN (SELECT id FROM public.locations "  # noqa: S608
                    f"WHERE organization_id = $1 AND (id = ${n} OR path <@ "
                    f"(SELECT path FROM public.locations WHERE organization_id = $1 AND id = ${n})))"
                )
            else:
                args.append(query.location_id)
                where.append(f"a.location_id = ${len(args)}")
        if query.holder_type is not None:
            column = {
                "member": "a.holder_member_id",
                "team": "a.holder_team_id",
                "location": "a.holder_location_id",
            }[query.holder_type]
            where.append(f"{column} IS NOT NULL")
        if query.holder_member_id is not None:
            args.append(query.holder_member_id)
            where.append(f"a.holder_member_id = ${len(args)}")
        if query.holder_team_id is not None:
            args.append(query.holder_team_id)
            where.append(f"a.holder_team_id = ${len(args)}")
        if query.criticality:
            args.append(list(query.criticality))
            where.append(f"a.criticality = ANY(${len(args)}::text[])")
        if query.manufacturer_id is not None:
            args.append(query.manufacturer_id)
            where.append(f"a.manufacturer_id = ${len(args)}")
        if query.supplier_id is not None:
            args.append(query.supplier_id)
            where.append(f"a.supplier_id = ${len(args)}")
        if query.warranty_end_before is not None:
            args.append(query.warranty_end_before)
            where.append(f"a.warranty_end < ${len(args)}::date")
        if query.warranty_end_after is not None:
            args.append(query.warranty_end_after)
            where.append(f"a.warranty_end > ${len(args)}::date")
        if query.purchase_date_before is not None:
            args.append(query.purchase_date_before)
            where.append(f"a.purchase_date < ${len(args)}::date")
        if query.purchase_date_after is not None:
            args.append(query.purchase_date_after)
            where.append(f"a.purchase_date > ${len(args)}::date")
        if query.updated_since is not None:
            args.append(query.updated_since)
            where.append(f"a.updated_at > ${len(args)}::timestamptz")
        for key, op, value in query.custom_field_filters:
            where.append(self._custom_field_clause(key, op, value, args))

        rank_select = f", {search_rank} AS search_rank" if search_rank else ""
        base_sql = f"SELECT {_BASE_COLUMNS}{rank_select}{_JOINS}WHERE {' AND '.join(where)}"

        total: int | None = None
        if include_total:
            total = await conn.fetchval(f"SELECT count(*) FROM ({base_sql}) t")  # noqa: S608

        order_sql, cursor_sql = self._order_and_cursor(
            sort=sort, search_rank=search_rank, after=after, args=args
        )
        full_where = f"WHERE {' AND '.join(where)}{cursor_sql}"
        sql = (
            f"SELECT {_BASE_COLUMNS}{rank_select}{_JOINS}{full_where} "
            f"ORDER BY {order_sql} LIMIT ${len(args) + 1}"
        )
        args.append(limit)
        rows = await conn.fetch(sql, *args)
        return rows, total

    def _order_and_cursor(
        self, *, sort: str, search_rank: str | None, after: str | None, args: list[Any]
    ) -> tuple[str, str]:
        if search_rank is not None:
            sort_expr, cast, desc = "search_rank", "::float8", True
        else:
            desc = sort.startswith("-")
            key = sort[1:] if desc else sort
            if key not in SORT_COLUMNS:
                from app.core.problems import FieldError, ValidationFailedError  # noqa: PLC0415

                raise ValidationFailedError(
                    errors=[FieldError(field="query.sort", message=f'unknown sort key "{key}"')]
                )
            column = SORT_COLUMNS[key]
            if key in _NULLABLE_SENTINELS:
                sentinel = _NULLABLE_SENTINELS[key][1 if desc else 0]
                sort_expr = f"COALESCE({column}, '{sentinel}'::date)"
            else:
                sort_expr = column
            cast = _CAST_BY_COLUMN.get(key, "")

        direction = "DESC" if desc else "ASC"
        order_sql = f"{sort_expr} {direction}, a.id {direction}"

        if after is None:
            return order_sql, ""
        value, record_id = decode_cursor(after)
        args.extend([value, record_id])
        op = "<" if desc else ">"
        value_arg = f"${len(args) - 1}{cast}"
        return order_sql, f" AND ({sort_expr}, a.id) {op} ({value_arg}, ${len(args)})"


def _try_uuid(value: str | None) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _is_number(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True
