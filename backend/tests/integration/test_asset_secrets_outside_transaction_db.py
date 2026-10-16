# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The secrets provider is never called inside a database transaction (PR #352 review, M1).

With OpenBao (production) every encrypt or decrypt is a network call. Made inside the write
transaction, a slow or unreachable OpenBao would hold a pooled connection, and on an edit the
asset's `FOR UPDATE` row lock, for as long as it waits. The provider double below asks PostgreSQL,
at the moment it is called, whether any session of the test database is inside a transaction.
Runs on the isolation suite's real PostgreSQL; only the secrets provider is a double.
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from collections.abc import Sequence
from pathlib import Path

import asyncpg
import pytest
from pg_harness import IsolationDb, PoolFactory

from app.core.db import Pool, tenant_transaction
from app.core.permissions import ScopeType
from app.core.problems import SecretsUnavailableError
from app.core.scope import MemberContext, RoleGrant
from app.modules.assets.schemas import AssetCreate, AssetUpdate
from app.modules.assets.service import create_asset, get_asset, update_asset
from app.providers.context import ProviderContext
from app.providers.secrets.base import SecretDecryptionError
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
INSERT_ENCRYPTED_FIELD = (
    "INSERT INTO public.custom_field_definitions "
    "(id, organization_id, category_id, key, label, field_type, is_encrypted) "
    "VALUES ($1, $2, $3, $4, $4, 'text', true)"
)
OPEN_TRANSACTIONS = (
    "SELECT count(*) FROM pg_stat_activity "
    "WHERE datname = current_database() AND pid <> pg_backend_pid() AND state LIKE 'idle in transaction%'"
)
FIELD = "badge_note"


def _token() -> str:
    return "t" + uuid.uuid4().hex[:12]


class _Probe(FileSecretsProvider):
    """A file provider that records, at every encrypt/decrypt, how many sessions are mid-transaction.
    With `fail=True` it then refuses the call, like an unreachable OpenBao."""

    def __init__(self, base: Path, admin_dsn: str, *, fail: bool = False) -> None:
        (base / "file.key").write_bytes(os.urandom(32))
        super().__init__(
            ProviderContext(env="test", pillar="secrets", base_dir=base), base, encryption_key_file="file.key"
        )
        self.admin_dsn, self.fail, self.open_transactions_seen = admin_dsn, fail, []

    async def _look(self) -> None:
        conn = await asyncpg.connect(self.admin_dsn)
        try:
            self.open_transactions_seen.append(await conn.fetchval(OPEN_TRANSACTIONS))
        finally:
            await conn.close()

    async def encrypt_many(self, items: Sequence[tuple[str, str]]) -> list[str]:
        await self._look()
        if self.fail:
            raise SecretsUnavailableError("unreachable")
        return await super().encrypt_many(items)

    async def decrypt_many(self, items: Sequence[tuple[str, str]]) -> list[str]:
        await self._look()
        if self.fail:
            raise SecretDecryptionError()
        return await super().decrypt_many(items)


@pytest.fixture
def config_base(tmp_path: Path) -> Path:
    """The fixture organizations use domain key `it`: serve the shipped asset template under it."""
    (tmp_path / "domains").mkdir()
    shutil.copy(REPO_DOMAINS / "it-assets.yaml", tmp_path / "domains" / "it.yaml")
    return tmp_path


async def _setup(pool: Pool, org: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    category_id, unit_id = uuid.uuid4(), uuid.uuid4()
    async with tenant_transaction(pool, org) as conn:
        await conn.execute(INSERT_CATEGORY, category_id, org, _token())
        await conn.execute(INSERT_ORG_UNIT, unit_id, org, _token())
        await conn.execute(INSERT_ENCRYPTED_FIELD, uuid.uuid4(), org, category_id, FIELD)
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


async def _stored(pool: Pool, org: uuid.UUID, name: str) -> list[dict[str, str]]:
    async with tenant_transaction(pool, org) as conn:
        rows = await conn.fetch(
            "SELECT encrypted_fields FROM public.assets WHERE organization_id = $1 AND name = $2", org, name
        )
    return [
        json.loads(r["encrypted_fields"])
        if isinstance(r["encrypted_fields"], str)
        else dict(r["encrypted_fields"])
        for r in rows
    ]


async def test_create_edit_and_read_call_the_provider_outside_any_transaction(
    make_pool: PoolFactory, isolation_db: IsolationDb, tmp_path: Path, config_base: Path
) -> None:
    pool, org = await make_pool("api"), isolation_db.org_a
    category_id, unit_id = await _setup(pool, org)
    probe = _Probe(tmp_path, isolation_db.admin_dsn)
    caller, name = _admin(org), _token()
    kwargs = {"organization_id": org, "caller": caller, "secrets_provider": probe}

    created = await create_asset(
        pool,
        data=AssetCreate(
            name=name, category_id=category_id, owner_org_unit_id=unit_id, custom_fields={FIELD: "first"}
        ),
        config_base_dir=config_base,
        **kwargs,
    )
    edited = await update_asset(
        pool,
        asset_id=created.id,
        data=AssetUpdate(version=created.version, custom_fields={FIELD: "second"}),
        config_base_dir=config_base,
        **kwargs,
    )
    read = await get_asset(pool, asset_id=created.id, **kwargs)

    assert created.encrypted_fields == {FIELD: "first"}
    assert edited.encrypted_fields == {FIELD: "second"}
    assert read.encrypted_fields == {FIELD: "second"}
    # create: encrypt + decrypt; edit: encrypt + decrypt; read: decrypt. None inside a transaction.
    assert probe.open_transactions_seen == [0, 0, 0, 0, 0]


async def test_an_unreachable_provider_on_create_writes_nothing_and_holds_no_transaction(
    make_pool: PoolFactory, isolation_db: IsolationDb, tmp_path: Path, config_base: Path
) -> None:
    pool, org = await make_pool("api"), isolation_db.org_a
    category_id, unit_id = await _setup(pool, org)
    probe = _Probe(tmp_path, isolation_db.admin_dsn, fail=True)
    name = _token()

    with pytest.raises(SecretsUnavailableError):
        await create_asset(
            pool,
            organization_id=org,
            caller=_admin(org),
            secrets_provider=probe,
            data=AssetCreate(
                name=name, category_id=category_id, owner_org_unit_id=unit_id, custom_fields={FIELD: "x"}
            ),
            config_base_dir=config_base,
        )

    assert probe.open_transactions_seen == [0]
    assert await _stored(pool, org, name) == []


async def test_an_unreachable_provider_on_edit_changes_nothing_and_holds_no_row_lock(
    make_pool: PoolFactory, isolation_db: IsolationDb, tmp_path: Path, config_base: Path
) -> None:
    pool, org = await make_pool("api"), isolation_db.org_a
    category_id, unit_id = await _setup(pool, org)
    caller, name = _admin(org), _token()
    (tmp_path / "ok").mkdir()
    working = _Probe(tmp_path / "ok", isolation_db.admin_dsn)
    created = await create_asset(
        pool,
        organization_id=org,
        caller=caller,
        secrets_provider=working,
        data=AssetCreate(
            name=name, category_id=category_id, owner_org_unit_id=unit_id, custom_fields={FIELD: "kept"}
        ),
        config_base_dir=config_base,
    )
    before = await _stored(pool, org, name)
    failing = _Probe(tmp_path, isolation_db.admin_dsn, fail=True)

    with pytest.raises(SecretsUnavailableError):
        await update_asset(
            pool,
            organization_id=org,
            caller=caller,
            secrets_provider=failing,
            asset_id=created.id,
            data=AssetUpdate(version=created.version, custom_fields={FIELD: "lost"}),
            config_base_dir=config_base,
        )

    assert failing.open_transactions_seen == [0]
    assert await _stored(pool, org, name) == before


async def test_a_failing_decrypt_on_read_holds_no_transaction(
    make_pool: PoolFactory, isolation_db: IsolationDb, tmp_path: Path, config_base: Path
) -> None:
    pool, org = await make_pool("api"), isolation_db.org_a
    category_id, unit_id = await _setup(pool, org)
    caller = _admin(org)
    (tmp_path / "ok").mkdir()
    created = await create_asset(
        pool,
        organization_id=org,
        caller=caller,
        secrets_provider=_Probe(tmp_path / "ok", isolation_db.admin_dsn),
        data=AssetCreate(
            name=_token(), category_id=category_id, owner_org_unit_id=unit_id, custom_fields={FIELD: "x"}
        ),
        config_base_dir=config_base,
    )
    failing = _Probe(tmp_path, isolation_db.admin_dsn, fail=True)

    with pytest.raises(SecretDecryptionError):
        await get_asset(
            pool, organization_id=org, caller=caller, secrets_provider=failing, asset_id=created.id
        )

    assert failing.open_transactions_seen == [0]
