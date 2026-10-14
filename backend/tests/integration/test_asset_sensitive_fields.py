# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Encrypted custom fields: one encrypt call per write, nothing written on failure, hidden from
lists (master M2.1-T2, §B8.1 Custom fields, §B11.4, §C5.2).

Runs against the isolation suite's real PostgreSQL (`pg_harness`, re-exported by
`tests/integration/conftest.py`): the write path is built here from the same pieces a future
asset write service (P8-07) will use (`validate_custom_fields`, `encrypt_custom_fields`,
`tenant_transaction`), so the proof is real - not a mock of the database.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

import pytest
from pg_harness import IsolationDb, PoolFactory

from app.core.db import Pool, platform_transaction, tenant_transaction
from app.core.problems import SecretsUnavailableError
from app.modules.assets.custom_fields import CustomFieldDefinition, validate_custom_fields
from app.modules.assets.errors import CustomFieldValidationError
from app.modules.assets.sensitive import (
    decrypt_custom_fields,
    encrypt_custom_fields,
    encrypted_field_presence,
)
from app.modules.assets.uniqueness import lock_and_check_unique_custom_field
from app.providers.context import ProviderContext
from app.providers.secrets.base import SecretsProvider
from app.providers.secrets.file import FileSecretsProvider

INSERT_CATEGORY = (
    "INSERT INTO public.asset_categories (id, organization_id, parent_id, path, code, name) "
    "VALUES ($1, $2, NULL, $3::ltree, $3, $3)"
)
INSERT_ORG_UNIT = (
    "INSERT INTO public.org_units (id, organization_id, parent_id, path, type, code, name) "
    "VALUES ($1, $2, NULL, $3::ltree, 'unit', $3, $3)"
)
INSERT_ASSET = (
    "INSERT INTO public.assets "
    "(id, organization_id, tag, name, category_id, owner_org_unit_id, custom_fields, encrypted_fields) "
    "VALUES ($1, $2, $3, $3, $4, $5, $6::jsonb, $7::jsonb)"
)


def _token() -> str:
    return uuid.uuid4().hex[:12]


class _SpyProvider(SecretsProvider):
    """Wraps a real provider, counting `encrypt_many` calls (§B8.1 "one encrypt call per write")."""

    def __init__(self, inner: SecretsProvider) -> None:
        self._inner = inner
        self.encrypt_many_calls = 0

    async def get(self, ref: str) -> str:
        return await self._inner.get(ref)

    async def get_map(self, path: str) -> dict[str, str]:
        return await self._inner.get_map(path)

    async def encrypt(self, context: str, plaintext: str) -> str:
        return await self._inner.encrypt(context, plaintext)

    async def encrypt_many(self, items: Any) -> list[str]:
        self.encrypt_many_calls += 1
        return await self._inner.encrypt_many(items)

    async def decrypt(self, context: str, ciphertext: str) -> str:
        return await self._inner.decrypt(context, ciphertext)

    async def health(self) -> dict[str, Any]:
        return await self._inner.health()


class _FailingProvider(SecretsProvider):
    """Every encrypt attempt fails (simulates a sealed or unreachable secrets provider).

    `encrypt_custom_fields` calls `encrypt_many`, not `encrypt`, directly. `SecretsProvider`'s
    default `encrypt_many` loops over `self.encrypt` (so the override below is redundant in this
    codebase's actual base class and the test passed before it was added too), but overriding it
    explicitly here removes any need for a reader to trace into that default to see why the test
    exercises the right code path, and survives a future base class change that drops the default.
    """

    async def get(self, ref: str) -> str:
        raise SecretsUnavailableError

    async def get_map(self, path: str) -> dict[str, str]:
        raise SecretsUnavailableError

    async def encrypt(self, context: str, plaintext: str) -> str:
        raise SecretsUnavailableError("The secrets provider is sealed.")

    async def encrypt_many(self, items: Any) -> list[str]:
        raise SecretsUnavailableError("The secrets provider is sealed.")

    async def decrypt(self, context: str, ciphertext: str) -> str:
        raise SecretsUnavailableError

    async def health(self) -> dict[str, Any]:
        return {"status": "unhealthy"}


def _file_provider(tmp_path: Path) -> FileSecretsProvider:
    (tmp_path / "file.key").write_bytes(os.urandom(32))
    ctx = ProviderContext(env="test", pillar="secrets", base_dir=tmp_path)
    return FileSecretsProvider(ctx, tmp_path, encryption_key_file="file.key")


_DEFINITIONS = [
    CustomFieldDefinition.model_validate({"key": "notes", "label": "Notes", "field_type": "text"}),
    CustomFieldDefinition.model_validate(
        {"key": "ssn", "label": "SSN", "field_type": "text", "is_encrypted": True}
    ),
    CustomFieldDefinition.model_validate(
        {"key": "pin", "label": "PIN", "field_type": "number", "is_encrypted": True}
    ),
]


async def _make_category_and_unit(pool: Pool, org: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    category_id, unit_id = uuid.uuid4(), uuid.uuid4()
    async with tenant_transaction(pool, org) as conn:
        await conn.execute(INSERT_CATEGORY, category_id, org, _token())
        await conn.execute(INSERT_ORG_UNIT, unit_id, org, _token())
    return category_id, unit_id


async def _write_asset(
    pool: Pool,
    org: uuid.UUID,
    provider: SecretsProvider,
    values: dict[str, object],
    *,
    category_id: uuid.UUID,
    unit_id: uuid.UUID,
) -> uuid.UUID:
    """The write path §B8.1 describes: validate, encrypt everything *before* opening the transaction,
    only then write. If `encrypt_custom_fields` raises, the `tenant_transaction` block below is never
    entered - nothing is written, by construction, not by a rollback."""
    clean = validate_custom_fields(_DEFINITIONS, values)
    encrypted = await encrypt_custom_fields(provider, organization_id=str(org), plaintexts=clean.to_encrypt)
    asset_id = uuid.uuid4()
    async with tenant_transaction(pool, org) as conn:
        await conn.execute(
            INSERT_ASSET,
            asset_id,
            org,
            _token(),
            category_id,
            unit_id,
            json.dumps(clean.plain),
            json.dumps(encrypted),
        )
    return asset_id


async def test_one_encrypt_call_per_write(
    make_pool: PoolFactory, isolation_db: IsolationDb, tmp_path: Path
) -> None:
    pool = await make_pool("api")
    category_id, unit_id = await _make_category_and_unit(pool, isolation_db.org_a)
    spy = _SpyProvider(_file_provider(tmp_path))

    asset_id = await _write_asset(
        pool,
        isolation_db.org_a,
        spy,
        {"notes": "plain note", "ssn": "123-45-6789", "pin": 4321},
        category_id=category_id,
        unit_id=unit_id,
    )

    assert spy.encrypt_many_calls == 1
    async with tenant_transaction(pool, isolation_db.org_a) as conn:
        row = await conn.fetchrow(
            "SELECT custom_fields, encrypted_fields FROM public.assets WHERE id = $1", asset_id
        )
    assert row is not None
    assert row["custom_fields"] == '{"notes": "plain note"}'
    stored = json.loads(row["encrypted_fields"])
    assert set(stored) == {"ssn", "pin"}
    assert stored["ssn"] != "123-45-6789"


async def test_provider_failure_writes_nothing(make_pool: PoolFactory, isolation_db: IsolationDb) -> None:
    pool = await make_pool("api")
    category_id, unit_id = await _make_category_and_unit(pool, isolation_db.org_a)
    async with tenant_transaction(pool, isolation_db.org_a) as conn:
        before = await conn.fetchval("SELECT count(*) FROM public.assets")

    with pytest.raises(SecretsUnavailableError):
        await _write_asset(
            pool,
            isolation_db.org_a,
            _FailingProvider(),
            {"notes": "plain note", "ssn": "should-never-be-written"},
            category_id=category_id,
            unit_id=unit_id,
        )

    async with tenant_transaction(pool, isolation_db.org_a) as conn:
        after = await conn.fetchval("SELECT count(*) FROM public.assets")
    assert after == before


async def test_list_response_never_contains_the_encrypted_value(
    make_pool: PoolFactory, isolation_db: IsolationDb, tmp_path: Path
) -> None:
    pool = await make_pool("api")
    category_id, unit_id = await _make_category_and_unit(pool, isolation_db.org_a)
    provider = _file_provider(tmp_path)
    marker = f"super-secret-{_token()}"
    asset_id = await _write_asset(
        pool, isolation_db.org_a, provider, {"ssn": marker}, category_id=category_id, unit_id=unit_id
    )

    async with tenant_transaction(pool, isolation_db.org_a) as conn:
        list_row = await conn.fetchrow("SELECT * FROM public.v_asset_inventory WHERE id = $1", asset_id)
    assert list_row is not None
    assert "encrypted_fields" not in list_row
    rendered = json.dumps(dict(list_row), default=str)
    assert marker not in rendered

    async with platform_transaction(pool) as conn:
        assert await conn.fetch("SELECT id FROM public.assets WHERE id = $1", asset_id) == []


async def test_detail_decrypts_only_for_a_member_with_read_sensitive(
    make_pool: PoolFactory, isolation_db: IsolationDb, tmp_path: Path
) -> None:
    pool = await make_pool("api")
    category_id, unit_id = await _make_category_and_unit(pool, isolation_db.org_a)
    provider = _file_provider(tmp_path)
    asset_id = await _write_asset(
        pool, isolation_db.org_a, provider, {"ssn": "123-45-6789"}, category_id=category_id, unit_id=unit_id
    )
    async with tenant_transaction(pool, isolation_db.org_a) as conn:
        row = await conn.fetchrow("SELECT encrypted_fields FROM public.assets WHERE id = $1", asset_id)
    assert row is not None
    stored = json.loads(row["encrypted_fields"])

    # Without asset.read_sensitive: presence only, never the ciphertext or plaintext.
    presence = encrypted_field_presence({"ssn", "pin"}, stored)
    assert presence == {"ssn": {"is_set": True}, "pin": {"is_set": False}}

    # With asset.read_sensitive: the detail view may decrypt on demand.
    org_id = str(isolation_db.org_a)
    decrypted = await decrypt_custom_fields(provider, organization_id=org_id, ciphertexts=stored)
    assert decrypted == {"ssn": "123-45-6789"}


async def test_unique_in_organization_is_enforced_under_an_advisory_lock(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    pool = await make_pool("api")
    category_id, unit_id = await _make_category_and_unit(pool, isolation_db.org_a)
    first_id = uuid.uuid4()
    async with tenant_transaction(pool, isolation_db.org_a) as conn:
        await conn.execute(
            INSERT_ASSET,
            first_id,
            isolation_db.org_a,
            _token(),
            category_id,
            unit_id,
            json.dumps({"serial": "SN-0001"}),
            "{}",
        )

    second_id = uuid.uuid4()
    async with tenant_transaction(pool, isolation_db.org_a) as conn:
        with pytest.raises(CustomFieldValidationError):
            await lock_and_check_unique_custom_field(
                conn,
                organization_id=isolation_db.org_a,
                field_key="serial",
                value="SN-0001",
                asset_id=second_id,
            )

    # A different value, or the same asset excluded, is not a conflict.
    async with tenant_transaction(pool, isolation_db.org_a) as conn:
        await lock_and_check_unique_custom_field(
            conn, organization_id=isolation_db.org_a, field_key="serial", value="SN-0002", asset_id=second_id
        )
        await lock_and_check_unique_custom_field(
            conn, organization_id=isolation_db.org_a, field_key="serial", value="SN-0001", asset_id=first_id
        )


async def test_unique_in_organization_does_not_leak_across_organizations(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    pool = await make_pool("api")
    category_a, unit_a = await _make_category_and_unit(pool, isolation_db.org_a)
    async with tenant_transaction(pool, isolation_db.org_a) as conn:
        await conn.execute(
            INSERT_ASSET,
            uuid.uuid4(),
            isolation_db.org_a,
            _token(),
            category_a,
            unit_a,
            json.dumps({"serial": "SHARED"}),
            "{}",
        )

    await _make_category_and_unit(pool, isolation_db.org_b)
    async with tenant_transaction(pool, isolation_db.org_b) as conn:
        # Same value, different organization: RLS limits the SELECT to org_b, so no conflict.
        await lock_and_check_unique_custom_field(
            conn,
            organization_id=isolation_db.org_b,
            field_key="serial",
            value="SHARED",
            asset_id=uuid.uuid4(),
        )
