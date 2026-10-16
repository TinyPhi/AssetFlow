# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""An `Idempotency-Key` replay of `POST /assets` (PR #352 review).

The replay used to return the stored asset before the `asset.create` check and without a scope
check, so a key worked like a bearer token for reading someone else's asset. Now: no `asset.create`
means 403 before any lookup; an asset outside the caller's read scope is a 404; a key reused with a
different body is a 422; a malformed or over-long key is a 422 before any lookup; and a key belongs
to the member who sent it, so another member's same key is a new request, never a replay.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.permissions import ScopeType
from app.core.problems import PermissionDeniedError, ValidationFailedError
from app.core.scope import MemberContext, RoleGrant
from app.modules.assets import service
from app.modules.assets.errors import AssetNotFoundError
from app.modules.assets.schemas import AssetCreate

ORG = uuid4()
CATEGORY = uuid4()
UNIT = uuid4()
CREATOR = uuid4()
SENTINEL: Any = object()


def _caller(
    role: str, scope: ScopeType = ScopeType.ORGANIZATION, path: str | None = None, member: UUID = CREATOR
) -> MemberContext:
    grant = RoleGrant(
        id="g",
        organization_id=str(ORG),
        role_key=role,
        scope_type=scope,
        scope_id=None if scope == ScopeType.ORGANIZATION else str(uuid4()),
        org_unit_path=path,
    )
    return MemberContext(member_id=str(member), organization_id=str(ORG), grants=(grant,))


def _body(name: str = "Pump 7") -> AssetCreate:
    return AssetCreate(name=name, category_id=CATEGORY, owner_org_unit_id=UNIT)


class _Repo:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self.row = row
        self.lookups = 0

    async def get_by_idempotency_key(
        self, conn: Any, *, organization_id: UUID, member_id: UUID, idempotency_key: str
    ) -> Any:
        self.lookups += 1
        return self.row if member_id == CREATOR else None

    async def get_detail(self, conn: Any, *, organization_id: UUID, asset_id: UUID) -> Any:
        return self.row


def _stored(path: str = "root.north") -> dict[str, Any]:
    return {
        "id": uuid4(),
        "name": "Pump 7",
        "category_id": CATEGORY,
        "owner_org_unit_id": UNIT,
        "owner_org_unit_path": path,
        "tag": "AST-00001",
        "holder_member_id": None,
        "holder_team_id": None,
    }


@pytest.fixture
def repo(monkeypatch: pytest.MonkeyPatch) -> _Repo:
    fake = _Repo(_stored())

    @asynccontextmanager
    async def _no_db(pool: Any, organization_id: UUID) -> AsyncIterator[object]:
        yield object()

    async def _read(conn: Any, detail: Any, **kwargs: Any) -> Any:
        return service._PendingRead(read=SENTINEL, ciphertexts={})

    monkeypatch.setattr(service, "tenant_transaction", _no_db)
    monkeypatch.setattr(service, "_asset_repo", fake)
    monkeypatch.setattr(service, "_to_asset_read", _read)
    return fake


async def _create(caller: MemberContext, key: str, body: AssetCreate | None = None) -> Any:
    return await service.create_asset(
        object(),  # type: ignore[arg-type]
        organization_id=ORG,
        caller=caller,
        secrets_provider=object(),  # type: ignore[arg-type]
        data=body or _body(),
        idempotency_key=key,
    )


async def test_a_replay_by_a_caller_without_asset_create_is_403_before_any_lookup(repo: _Repo) -> None:
    with pytest.raises(PermissionDeniedError):
        await _create(_caller("member"), "replay-key-1")
    assert repo.lookups == 0


async def test_a_replay_of_an_asset_outside_the_callers_scope_is_404(repo: _Repo) -> None:
    south_admin = _caller("admin", ScopeType.ORG_UNIT, "root.south")
    with pytest.raises(AssetNotFoundError):
        await _create(south_admin, "replay-key-1")


async def test_a_key_reused_with_a_different_body_is_422(repo: _Repo) -> None:
    with pytest.raises(ValidationFailedError):
        await _create(_caller("admin"), "replay-key-1", _body(name="Another asset"))


async def test_the_same_request_from_a_caller_who_may_read_it_is_replayed(repo: _Repo) -> None:
    assert await _create(_caller("admin"), "replay-key-1") is SENTINEL


async def test_the_same_key_from_another_member_is_a_new_request_not_a_replay(repo: _Repo) -> None:
    other_admin = _caller("admin", member=uuid4())
    replayed = await service._replay_create(
        object(),  # type: ignore[arg-type]
        organization_id=ORG,
        caller=other_admin,
        secrets_provider=object(),  # type: ignore[arg-type]
        data=_body(),
        idempotency_key="replay-key-1",
    )
    assert replayed is None and repo.lookups == 1


@pytest.mark.parametrize("key", ["", "x" * 256, "has space", "non-ascii-é"])
async def test_a_malformed_or_over_long_key_is_422_before_any_lookup(repo: _Repo, key: str) -> None:
    with pytest.raises(ValidationFailedError):
        await _create(_caller("admin"), key)
    assert repo.lookups == 0
