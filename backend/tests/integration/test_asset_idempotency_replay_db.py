# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""`Idempotency-Key` replay rules against a real PostgreSQL (PR #352 review, #359).

`tests/unit/test_asset_idempotency_replay.py` fakes the repository, so the real lookup
(`WHERE organization_id = $1 AND idempotency_member_id = $2 AND idempotency_key = $3`) and the
schema's key rules were never exercised. These tests run `create_asset` end to end on the isolation
suite's real database, with no fakes.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from pathlib import Path

import pytest
from pg_harness import IsolationDb, PoolFactory

from app.core.db import Pool, tenant_transaction
from app.core.permissions import ScopeType
from app.core.problems import PermissionDeniedError, ValidationFailedError
from app.core.scope import MemberContext, RoleGrant
from app.modules.assets.errors import AssetNotFoundError
from app.modules.assets.schemas import AssetCreate
from app.modules.assets.service import create_asset
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
INSERT_MEMBER = (
    "INSERT INTO public.members (id, organization_id, email, status, idp_subject, display_name) "
    "VALUES ($1, $2, $3 || '@example.test', 'active', $3, $3)"
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
def provider(tmp_path: Path) -> FileSecretsProvider:
    (tmp_path / "file.key").write_bytes(os.urandom(32))
    return FileSecretsProvider(
        ProviderContext(env="test", pillar="secrets", base_dir=tmp_path),
        tmp_path,
        encryption_key_file="file.key",
    )


async def _setup(pool: Pool, org: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID, str, uuid.UUID, uuid.UUID]:
    category_id, unit_id, unit_path = uuid.uuid4(), uuid.uuid4(), _token()
    member_a, member_b = uuid.uuid4(), uuid.uuid4()
    async with tenant_transaction(pool, org) as conn:
        await conn.execute(INSERT_CATEGORY, category_id, org, _token())
        await conn.execute(INSERT_ORG_UNIT, unit_id, org, unit_path)
        await conn.execute(INSERT_MEMBER, member_a, org, _token())
        await conn.execute(INSERT_MEMBER, member_b, org, _token())
    return category_id, unit_id, unit_path, member_a, member_b


def _caller(
    org: uuid.UUID, member: uuid.UUID, *, org_unit_path: str | None = None, role: str = "admin"
) -> MemberContext:
    scope = ScopeType.ORG_UNIT if org_unit_path is not None else ScopeType.ORGANIZATION
    return MemberContext(
        member_id=str(member),
        organization_id=str(org),
        grants=(
            RoleGrant(
                id="g",
                organization_id=str(org),
                role_key=role,
                scope_type=scope,
                scope_id=str(uuid.uuid4()) if org_unit_path is not None else None,
                org_unit_path=org_unit_path,
            ),
        ),
    )


def _body(category_id: uuid.UUID, unit_id: uuid.UUID, name: str = "Replay asset") -> AssetCreate:
    return AssetCreate(name=name, category_id=category_id, owner_org_unit_id=unit_id)


async def _count_with_key(pool: Pool, org: uuid.UUID, key: str) -> int:
    async with tenant_transaction(pool, org) as conn:
        count: int = await conn.fetchval(
            "SELECT count(*) FROM public.assets WHERE organization_id = $1 AND idempotency_key = $2", org, key
        )
    return count


async def test_the_same_member_replaying_the_same_request_gets_the_same_asset(
    make_pool: PoolFactory, isolation_db: IsolationDb, provider: FileSecretsProvider, config_base: Path
) -> None:
    pool, org = await make_pool("api"), isolation_db.org_a
    category_id, unit_id, _, member_a, _ = await _setup(pool, org)
    key = str(uuid.uuid4())
    caller = _caller(org, member_a)
    kwargs = {"organization_id": org, "secrets_provider": provider, "config_base_dir": config_base}

    first = await create_asset(
        pool, caller=caller, data=_body(category_id, unit_id), idempotency_key=key, **kwargs
    )
    second = await create_asset(
        pool, caller=caller, data=_body(category_id, unit_id), idempotency_key=key, **kwargs
    )

    assert first.id == second.id
    assert await _count_with_key(pool, org, key) == 1


async def test_another_members_key_never_replays_their_asset(
    make_pool: PoolFactory, isolation_db: IsolationDb, provider: FileSecretsProvider, config_base: Path
) -> None:
    """A key belongs to the member who sent it: the same key from another member creates a new asset."""
    pool, org = await make_pool("api"), isolation_db.org_a
    category_id, unit_id, _, member_a, member_b = await _setup(pool, org)
    key = str(uuid.uuid4())
    kwargs = {"organization_id": org, "secrets_provider": provider, "config_base_dir": config_base}

    by_a = await create_asset(
        pool, caller=_caller(org, member_a), data=_body(category_id, unit_id), idempotency_key=key, **kwargs
    )
    by_b = await create_asset(
        pool, caller=_caller(org, member_b), data=_body(category_id, unit_id), idempotency_key=key, **kwargs
    )

    assert by_a.id != by_b.id
    assert await _count_with_key(pool, org, key) == 2


async def test_a_replay_outside_the_callers_read_scope_is_a_404(
    make_pool: PoolFactory, isolation_db: IsolationDb, provider: FileSecretsProvider, config_base: Path
) -> None:
    pool, org = await make_pool("api"), isolation_db.org_a
    category_id, unit_id, _, member_a, _ = await _setup(pool, org)
    key = str(uuid.uuid4())
    kwargs = {"organization_id": org, "secrets_provider": provider, "config_base_dir": config_base}
    await create_asset(
        pool, caller=_caller(org, member_a), data=_body(category_id, unit_id), idempotency_key=key, **kwargs
    )

    # The same member, now holding asset rights only in another org unit.
    narrowed = _caller(org, member_a, org_unit_path=_token())
    with pytest.raises(AssetNotFoundError):
        await create_asset(
            pool, caller=narrowed, data=_body(category_id, unit_id), idempotency_key=key, **kwargs
        )
    assert await _count_with_key(pool, org, key) == 1


async def test_a_key_reused_with_a_different_body_is_a_422(
    make_pool: PoolFactory, isolation_db: IsolationDb, provider: FileSecretsProvider, config_base: Path
) -> None:
    pool, org = await make_pool("api"), isolation_db.org_a
    category_id, unit_id, _, member_a, _ = await _setup(pool, org)
    key = str(uuid.uuid4())
    caller = _caller(org, member_a)
    kwargs = {"organization_id": org, "secrets_provider": provider, "config_base_dir": config_base}
    await create_asset(pool, caller=caller, data=_body(category_id, unit_id), idempotency_key=key, **kwargs)

    with pytest.raises(ValidationFailedError):
        await create_asset(
            pool,
            caller=caller,
            data=_body(category_id, unit_id, name="Another asset"),
            idempotency_key=key,
            **kwargs,
        )
    assert await _count_with_key(pool, org, key) == 1


async def test_a_caller_without_asset_create_is_refused_before_any_replay(
    make_pool: PoolFactory, isolation_db: IsolationDb, provider: FileSecretsProvider, config_base: Path
) -> None:
    pool, org = await make_pool("api"), isolation_db.org_a
    category_id, unit_id, _, member_a, _ = await _setup(pool, org)
    key = str(uuid.uuid4())
    kwargs = {"organization_id": org, "secrets_provider": provider, "config_base_dir": config_base}
    await create_asset(
        pool, caller=_caller(org, member_a), data=_body(category_id, unit_id), idempotency_key=key, **kwargs
    )

    reader = _caller(org, member_a, role="member")  # asset.read, no asset.create
    with pytest.raises(PermissionDeniedError):
        await create_asset(
            pool, caller=reader, data=_body(category_id, unit_id), idempotency_key=key, **kwargs
        )


@pytest.mark.parametrize("key", ["", "x" * 256, "has space", "tab\tkey", "naïve"])
async def test_a_malformed_key_is_a_422_and_writes_nothing(
    make_pool: PoolFactory,
    isolation_db: IsolationDb,
    provider: FileSecretsProvider,
    config_base: Path,
    key: str,
) -> None:
    pool, org = await make_pool("api"), isolation_db.org_a
    category_id, unit_id, _, member_a, _ = await _setup(pool, org)
    with pytest.raises(ValidationFailedError):
        await create_asset(
            pool,
            organization_id=org,
            caller=_caller(org, member_a),
            secrets_provider=provider,
            data=_body(category_id, unit_id, name=f"Malformed {uuid.uuid4().hex[:6]}"),
            idempotency_key=key,
            config_base_dir=config_base,
        )
    async with tenant_transaction(pool, org) as conn:
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM public.assets WHERE organization_id = $1 AND category_id = $2",
                org,
                category_id,
            )
            == 0
        )


async def test_concurrent_creates_with_the_same_key_all_return_the_one_asset(
    make_pool: PoolFactory, isolation_db: IsolationDb, provider: FileSecretsProvider, config_base: Path
) -> None:
    """#360: requests with the same key in flight at once used to race past the replay check; the
    loser hit the key's unique index and got a 500. Now every request returns the one stored asset."""
    pool, org = await make_pool("api"), isolation_db.org_a
    category_id, unit_id, _, member_a, _ = await _setup(pool, org)
    key = str(uuid.uuid4())
    caller = _caller(org, member_a)

    results = await asyncio.gather(
        *(
            create_asset(
                pool,
                organization_id=org,
                caller=caller,
                secrets_provider=provider,
                data=_body(category_id, unit_id),
                idempotency_key=key,
                config_base_dir=config_base,
            )
            for _ in range(8)
        )
    )

    assert len({r.id for r in results}) == 1
    assert await _count_with_key(pool, org, key) == 1
