# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""`criticality` is text validated from config (PR #352 review, M2).

Create and edit accept only a level from the organization's domain template (`assets.criticality`).
With no template there are no levels, so only an empty value is accepted. Runs on the isolation
suite's real PostgreSQL, with no fakes.
"""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

import pytest
from pg_harness import IsolationDb, PoolFactory

from app.core.db import Pool, tenant_transaction
from app.core.permissions import ScopeType
from app.core.problems import ValidationFailedError
from app.core.scope import MemberContext, RoleGrant
from app.modules.assets.schemas import AssetCreate, AssetUpdate
from app.modules.assets.service import create_asset, update_asset
from app.providers.context import ProviderContext
from app.providers.secrets.file import FileSecretsProvider

REPO_DOMAINS = Path(__file__).resolve().parents[3] / "config" / "domains"

INSERT_CATEGORY = (
    "INSERT INTO public.asset_categories (id, organization_id, parent_id, path, code, name) "
    "VALUES ($1, $2, NULL, $3::ltree, $3, $3)"
)
INSERT_ORG_UNIT = (
    "INSERT INTO public.org_units (id, organization_id, parent_id, path, type, code, name) "
    "VALUES ($1, $2, NULL, $3::ltree, 'unit', $3, $3)"
)


def _token() -> str:
    return "t" + uuid.uuid4().hex[:12]


@pytest.fixture
def config_base(tmp_path: Path) -> Path:
    """The fixture organizations use domain key `it`: serve the shipped asset template under it."""
    (tmp_path / "domains").mkdir()
    shutil.copy(REPO_DOMAINS / "it-assets.yaml", tmp_path / "domains" / "it.yaml")
    return tmp_path


@pytest.fixture
def no_template(tmp_path: Path) -> Path:
    base = tmp_path / "empty"
    (base / "domains").mkdir(parents=True)
    return base


@pytest.fixture
def provider(tmp_path: Path) -> FileSecretsProvider:
    (tmp_path / "file.key").write_bytes(os.urandom(32))
    return FileSecretsProvider(
        ProviderContext(env="test", pillar="secrets", base_dir=tmp_path),
        tmp_path,
        encryption_key_file="file.key",
    )


async def _setup(pool: Pool, org: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    category_id, unit_id = uuid.uuid4(), uuid.uuid4()
    async with tenant_transaction(pool, org) as conn:
        await conn.execute(INSERT_CATEGORY, category_id, org, _token())
        await conn.execute(INSERT_ORG_UNIT, unit_id, org, _token())
    return category_id, unit_id


def _admin(org: uuid.UUID) -> MemberContext:
    return MemberContext(
        member_id=str(uuid.uuid4()),
        organization_id=str(org),
        grants=(
            RoleGrant(
                id="g",
                organization_id=str(org),
                role_key="admin",
                scope_type=ScopeType.ORGANIZATION,
                scope_id=None,
                org_unit_path=None,
            ),
        ),
    )


async def _stored_criticality(pool: Pool, org: uuid.UUID, name: str) -> list[str | None]:
    async with tenant_transaction(pool, org) as conn:
        rows = await conn.fetch(
            "SELECT criticality FROM public.assets WHERE organization_id = $1 AND name = $2", org, name
        )
    return [r["criticality"] for r in rows]


async def test_create_with_a_template_level_is_stored(
    make_pool: PoolFactory, isolation_db: IsolationDb, provider: FileSecretsProvider, config_base: Path
) -> None:
    pool, org = await make_pool("api"), isolation_db.org_a
    category_id, unit_id = await _setup(pool, org)
    name = _token()

    asset = await create_asset(
        pool,
        organization_id=org,
        caller=_admin(org),
        secrets_provider=provider,
        data=AssetCreate(name=name, category_id=category_id, owner_org_unit_id=unit_id, criticality="high"),
        config_base_dir=config_base,
    )

    assert asset.criticality == "high"


async def test_create_with_an_unknown_criticality_is_a_422_and_writes_nothing(
    make_pool: PoolFactory, isolation_db: IsolationDb, provider: FileSecretsProvider, config_base: Path
) -> None:
    pool, org = await make_pool("api"), isolation_db.org_a
    category_id, unit_id = await _setup(pool, org)
    name = _token()

    with pytest.raises(ValidationFailedError) as caught:
        await create_asset(
            pool,
            organization_id=org,
            caller=_admin(org),
            secrets_provider=provider,
            data=AssetCreate(
                name=name, category_id=category_id, owner_org_unit_id=unit_id, criticality="urgent-ish"
            ),
            config_base_dir=config_base,
        )

    assert [e.field for e in caught.value.errors] == ["criticality"]
    assert await _stored_criticality(pool, org, name) == []


async def test_create_without_a_template_refuses_any_criticality(
    make_pool: PoolFactory, isolation_db: IsolationDb, provider: FileSecretsProvider, no_template: Path
) -> None:
    """No template means no levels. (Create without a template is refused anyway for its missing tag
    format; this checks the criticality is refused first, on its own field.)"""
    pool, org = await make_pool("api"), isolation_db.org_a
    category_id, unit_id = await _setup(pool, org)

    with pytest.raises(ValidationFailedError) as caught:
        await create_asset(
            pool,
            organization_id=org,
            caller=_admin(org),
            secrets_provider=provider,
            data=AssetCreate(
                name=_token(), category_id=category_id, owner_org_unit_id=unit_id, criticality="high"
            ),
            config_base_dir=no_template,
        )

    assert [e.field for e in caught.value.errors] == ["criticality"]


async def test_edit_with_an_unknown_criticality_is_a_422_and_changes_nothing(
    make_pool: PoolFactory, isolation_db: IsolationDb, provider: FileSecretsProvider, config_base: Path
) -> None:
    pool, org = await make_pool("api"), isolation_db.org_a
    category_id, unit_id = await _setup(pool, org)
    caller, name = _admin(org), _token()
    kwargs = {
        "organization_id": org,
        "caller": caller,
        "secrets_provider": provider,
        "config_base_dir": config_base,
    }
    asset = await create_asset(
        pool,
        data=AssetCreate(name=name, category_id=category_id, owner_org_unit_id=unit_id, criticality="low"),
        **kwargs,
    )

    with pytest.raises(ValidationFailedError) as caught:
        await update_asset(
            pool,
            asset_id=asset.id,
            data=AssetUpdate(version=asset.version, criticality="urgent-ish"),
            **kwargs,
        )
    assert [e.field for e in caught.value.errors] == ["criticality"]
    assert await _stored_criticality(pool, org, name) == ["low"]

    edited = await update_asset(
        pool, asset_id=asset.id, data=AssetUpdate(version=asset.version, criticality="critical"), **kwargs
    )
    assert edited.criticality == "critical"
