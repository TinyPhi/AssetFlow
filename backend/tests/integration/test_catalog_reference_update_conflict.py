# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Renaming a manufacturer/supplier to an existing name must 409, not 500 (PR #289 blocker 3).

`_create_reference` checks name uniqueness before insert; `_update_reference` skipped the same
check and called the repository directly, so a rename collision surfaced as an uncaught
`asyncpg.UniqueViolationError` instead of the domain `ManufacturerConflictError`/`SupplierConflictError`.
"""

from __future__ import annotations

import uuid

import pytest
from pg_harness import IsolationDb, PoolFactory

from app.core.scope import MemberContext, RoleGrant, ScopeType
from app.modules.assets.catalog.errors import ManufacturerConflictError, SupplierConflictError
from app.modules.assets.catalog.schemas import (
    ManufacturerCreate,
    ManufacturerUpdate,
    SupplierCreate,
    SupplierUpdate,
)
from app.modules.assets.catalog.service import (
    create_manufacturer,
    create_supplier,
    update_manufacturer,
    update_supplier,
)


def _caller(organization_id: uuid.UUID) -> MemberContext:
    return MemberContext(
        member_id=str(uuid.uuid4()),
        organization_id=str(organization_id),
        grants=(
            RoleGrant(
                id="g",
                organization_id=str(organization_id),
                role_key="admin",
                scope_type=ScopeType.ORGANIZATION,
            ),
        ),
    )


async def test_renaming_a_manufacturer_to_an_existing_name_is_a_conflict_not_a_500(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    pool = await make_pool("api")
    org = isolation_db.org_a
    caller = _caller(org)

    taken = await create_manufacturer(
        pool, organization_id=org, caller=caller, data=ManufacturerCreate(code=None, name="Acme Corp")
    )
    renaming = await create_manufacturer(
        pool, organization_id=org, caller=caller, data=ManufacturerCreate(code=None, name="Other Corp")
    )

    with pytest.raises(ManufacturerConflictError):
        await update_manufacturer(
            pool,
            organization_id=org,
            caller=caller,
            manufacturer_id=renaming.id,
            data=ManufacturerUpdate(name=taken.name, version=renaming.version),
        )

    # Renaming to its own current name, or to a name nobody holds, is still allowed.
    updated = await update_manufacturer(
        pool,
        organization_id=org,
        caller=caller,
        manufacturer_id=renaming.id,
        data=ManufacturerUpdate(name="Renaming Corp", version=renaming.version),
    )
    assert updated.name == "Renaming Corp"


async def test_renaming_a_supplier_to_an_existing_name_is_a_conflict_not_a_500(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    pool = await make_pool("api")
    org = isolation_db.org_b
    caller = _caller(org)

    taken = await create_supplier(
        pool, organization_id=org, caller=caller, data=SupplierCreate(code=None, name="Acme Supply")
    )
    renaming = await create_supplier(
        pool, organization_id=org, caller=caller, data=SupplierCreate(code=None, name="Other Supply")
    )

    with pytest.raises(SupplierConflictError):
        await update_supplier(
            pool,
            organization_id=org,
            caller=caller,
            supplier_id=renaming.id,
            data=SupplierUpdate(name=taken.name, version=renaming.version),
        )
