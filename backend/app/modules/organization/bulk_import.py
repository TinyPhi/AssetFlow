# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Bulk import of org units, teams and members: preview, then atomic commit (§B10, M1.4-T7).

Named `bulk_import`, not `import` (the plan's suggested name): `import` is a Python keyword and
cannot be a module name.

Rows are structured data (JSON), not raw spreadsheet bytes: parsing a specific file format
(xlsx/csv) is a later, larger plan item (master plan §B7.3, M2.3-T1), out of scope here. A row
references another row or an existing record only by its business code/email, never by id (ids
do not exist yet for new rows); within one import, a child org unit or a team/member referencing
an org unit must list that org unit earlier in the same `org_units` list (parents before
children) — the simplest ordering rule that still allows a one-shot hierarchical import.

Preview (`dry_run=True`) validates every row and writes nothing. Commit runs every row in one
transaction: any row error raises before any write is visible outside it (the caller's
`tenant_transaction` rolls back), and on success writes one audit event and one outbox row for the
whole import, not one per row (its payload would otherwise defeat the no-PII-in-logs rule at any
real import size). A row whose business key already exists is skipped, not duplicated or errored,
so committing the same import twice is a no-op the second time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

import asyncpg
from pydantic import BaseModel, ConfigDict

from app.core.ids import uuid7
from app.core.problems import FieldError, ValidationFailedError
from app.modules.audit.service import record_audit_event
from app.modules.organization.repository import to_ltree_label

type DbConn = asyncpg.Connection[asyncpg.Record] | asyncpg.pool.PoolConnectionProxy[asyncpg.Record]

MAX_ROWS_PER_SECTION = 500
IMPORT_COMMITTED_EVENT = "import.committed"


class OrgUnitRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    name: str
    type: str
    parent_code: str | None = None


class TeamRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    name: str
    type: str
    owning_org_unit_code: str | None = None


class MemberRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    display_name: str
    primary_org_unit_code: str | None = None


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    org_units: list[OrgUnitRow] = []
    teams: list[TeamRow] = []
    members: list[MemberRow] = []


Section = Literal["org_units", "teams", "members"]


@dataclass(frozen=True)
class SectionResult:
    created: int = 0
    skipped: int = 0


@dataclass(frozen=True)
class ImportResult:
    org_units: SectionResult = field(default_factory=SectionResult)
    teams: SectionResult = field(default_factory=SectionResult)
    members: SectionResult = field(default_factory=SectionResult)

    def as_dict(self) -> dict[str, Any]:
        return {
            section: {"created": r.created, "skipped": r.skipped}
            for section, r in (
                ("org_units", self.org_units),
                ("teams", self.teams),
                ("members", self.members),
            )
        }


def _row_error(section: Section, index: int, field_name: str, message: str) -> FieldError:
    return FieldError(field=f"{section}[{index}].{field_name}", message=message)


def _check_row_limits(data: ImportRequest) -> None:
    for section_name, rows in (
        ("org_units", data.org_units),
        ("teams", data.teams),
        ("members", data.members),
    ):
        if len(rows) > MAX_ROWS_PER_SECTION:
            raise ValidationFailedError(
                f"{section_name} has {len(rows)} rows; the limit is {MAX_ROWS_PER_SECTION} per import"
            )


async def _resolve_org_unit(
    conn: DbConn, organization_id: UUID, code: str, created: dict[str, UUID]
) -> UUID | None:
    if code in created:
        return created[code]
    found: UUID | None = await conn.fetchval(
        "SELECT id FROM public.org_units WHERE organization_id = $1 AND code = $2", organization_id, code
    )
    return found


async def _process_org_units(
    conn: DbConn, organization_id: UUID, rows: list[OrgUnitRow], *, dry_run: bool, errors: list[FieldError]
) -> tuple[SectionResult, dict[str, UUID]]:
    created: dict[str, UUID] = {}
    seen_codes: set[str] = set()
    created_count = skipped_count = 0
    for i, row in enumerate(rows):
        if row.code in seen_codes:
            errors.append(_row_error("org_units", i, "code", f"duplicate code {row.code!r} in this import"))
            continue
        seen_codes.add(row.code)

        existing_id = await conn.fetchval(
            "SELECT id FROM public.org_units WHERE organization_id = $1 AND code = $2",
            organization_id,
            row.code,
        )
        if existing_id is not None:
            created[row.code] = existing_id
            skipped_count += 1
            continue

        parent_id: UUID | None = None
        parent_path: str | None = None
        if row.parent_code is not None:
            parent_id = await _resolve_org_unit(conn, organization_id, row.parent_code, created)
            if parent_id is None:
                errors.append(
                    _row_error(
                        "org_units",
                        i,
                        "parent_code",
                        f"{row.parent_code!r} is not an existing org unit or an earlier row in this import",
                    )
                )
                continue
            parent_path = await conn.fetchval(
                "SELECT path FROM public.org_units WHERE organization_id = $1 AND id = $2",
                organization_id,
                parent_id,
            )

        try:
            label = to_ltree_label(row.code)
        except ValueError:
            errors.append(_row_error("org_units", i, "code", f"{row.code!r} cannot form a valid path label"))
            continue
        path = f"{parent_path}.{label}" if parent_path else label

        if dry_run:
            created[row.code] = uuid7()  # a placeholder so later rows can resolve this one
            created_count += 1
            continue

        unit_id = uuid7()
        await conn.execute(
            "INSERT INTO public.org_units (id, organization_id, parent_id, path, type, code, name)"
            " VALUES ($1, $2, $3, $4::ltree, $5, $6, $7)",
            unit_id,
            organization_id,
            parent_id,
            path,
            row.type,
            row.code,
            row.name,
        )
        created[row.code] = unit_id
        created_count += 1
    return SectionResult(created=created_count, skipped=skipped_count), created


async def _process_teams(
    conn: DbConn,
    organization_id: UUID,
    rows: list[TeamRow],
    *,
    dry_run: bool,
    org_units_created: dict[str, UUID],
    errors: list[FieldError],
) -> SectionResult:
    seen_codes: set[str] = set()
    created_count = skipped_count = 0
    for i, row in enumerate(rows):
        if row.code in seen_codes:
            errors.append(_row_error("teams", i, "code", f"duplicate code {row.code!r} in this import"))
            continue
        seen_codes.add(row.code)

        existing_id = await conn.fetchval(
            "SELECT id FROM public.teams WHERE organization_id = $1 AND code = $2", organization_id, row.code
        )
        if existing_id is not None:
            skipped_count += 1
            continue

        owning_org_unit_id: UUID | None = None
        if row.owning_org_unit_code is not None:
            owning_org_unit_id = await _resolve_org_unit(
                conn, organization_id, row.owning_org_unit_code, org_units_created
            )
            if owning_org_unit_id is None:
                errors.append(
                    _row_error(
                        "teams",
                        i,
                        "owning_org_unit_code",
                        f"{row.owning_org_unit_code!r} is not an existing or imported org unit",
                    )
                )
                continue

        if dry_run:
            created_count += 1
            continue

        await conn.execute(
            "INSERT INTO public.teams (id, organization_id, code, name, type, owning_org_unit_id)"
            " VALUES ($1, $2, $3, $4, $5, $6)",
            uuid7(),
            organization_id,
            row.code,
            row.name,
            row.type,
            owning_org_unit_id,
        )
        created_count += 1
    return SectionResult(created=created_count, skipped=skipped_count)


async def _process_members(
    conn: DbConn,
    organization_id: UUID,
    rows: list[MemberRow],
    *,
    dry_run: bool,
    org_units_created: dict[str, UUID],
    errors: list[FieldError],
) -> SectionResult:
    seen_emails: set[str] = set()
    created_count = skipped_count = 0
    for i, row in enumerate(rows):
        email_key = row.email.lower()
        if email_key in seen_emails:
            errors.append(_row_error("members", i, "email", f"duplicate email {row.email!r} in this import"))
            continue
        seen_emails.add(email_key)

        existing_id = await conn.fetchval(
            "SELECT id FROM public.members WHERE organization_id = $1 AND lower(email) = $2",
            organization_id,
            email_key,
        )
        if existing_id is not None:
            skipped_count += 1
            continue

        primary_org_unit_id: UUID | None = None
        if row.primary_org_unit_code is not None:
            primary_org_unit_id = await _resolve_org_unit(
                conn, organization_id, row.primary_org_unit_code, org_units_created
            )
            if primary_org_unit_id is None:
                errors.append(
                    _row_error(
                        "members",
                        i,
                        "primary_org_unit_code",
                        f"{row.primary_org_unit_code!r} is not an existing or imported org unit",
                    )
                )
                continue

        if dry_run:
            created_count += 1
            continue

        await conn.execute(
            "INSERT INTO public.members"
            " (id, organization_id, idp_subject, email, display_name, primary_org_unit_id, status)"
            " VALUES ($1, $2, $3, $4, $5, $6, 'invited')",
            uuid7(),
            organization_id,
            f"pending-invite:{row.email}",
            row.email,
            row.display_name,
            primary_org_unit_id,
        )
        created_count += 1
    return SectionResult(created=created_count, skipped=skipped_count)


async def run_import(
    conn: DbConn,
    *,
    organization_id: UUID,
    data: ImportRequest,
    dry_run: bool,
    actor_member_id: UUID | None = None,
    request_id: str | None = None,
) -> ImportResult:
    """Validate (and, unless `dry_run`, write) every row. Raises `ValidationFailedError` (its
    `errors` list has one `FieldError` per bad row) when any row fails, writing nothing."""
    _check_row_limits(data)
    errors: list[FieldError] = []

    org_units_result, org_units_created = await _process_org_units(
        conn, organization_id, data.org_units, dry_run=dry_run, errors=errors
    )
    teams_result = await _process_teams(
        conn,
        organization_id,
        data.teams,
        dry_run=dry_run,
        org_units_created=org_units_created,
        errors=errors,
    )
    members_result = await _process_members(
        conn,
        organization_id,
        data.members,
        dry_run=dry_run,
        org_units_created=org_units_created,
        errors=errors,
    )

    if errors:
        raise ValidationFailedError("Import has invalid rows; nothing was written.", errors=errors)

    result = ImportResult(org_units=org_units_result, teams=teams_result, members=members_result)
    if dry_run:
        return result

    import_id = uuid7()
    await record_audit_event(
        conn,
        organization_id=organization_id,
        actor_member_id=actor_member_id,
        action="import.commit",
        entity_type="import",
        entity_id=import_id,
        request_id=request_id,
        after_state=result.as_dict(),
    )
    await conn.execute(
        "INSERT INTO public.outbox (id, organization_id, event_type, aggregate_type, aggregate_id, payload) "
        "VALUES ($1, $2, $3, 'import', $1, '{}'::jsonb)",
        import_id,
        organization_id,
        IMPORT_COMMITTED_EVENT,
    )
    return result
