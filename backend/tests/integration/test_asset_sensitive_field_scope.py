# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""`get_asset` must scope-check `asset.read_sensitive`, not just check the caller holds it anywhere
(PR #290 review, still-open finding carried from a prior review pass).

`_to_asset_read` used `has_permission(caller, READ_SENSITIVE_PERMISSION)`, an org-wide check with
no resource argument. A caller holding `read_sensitive` only at `self` scope (i.e. "my own held
assets") would still see the decrypted sensitive fields of *any* asset they can generally read,
including one held by someone else. Fixed to `check_access(..., _resource(row))`, matching the
pattern every other record-level check in this module already uses.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from pg_harness import IsolationDb, PoolFactory

from app.core.db import tenant_transaction
from app.core.permissions import ScopeType
from app.core.scope import MemberContext, RoleGrant
from app.modules.assets.sensitive import encrypt_custom_fields
from app.modules.assets.service import get_asset
from app.providers.context import ProviderContext
from app.providers.secrets.file import FileSecretsProvider

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
    "VALUES ($1, $2, $3, 'active', $4, $3)"
)
INSERT_ASSET = (
    "INSERT INTO public.assets "
    "(id, organization_id, tag, name, category_id, owner_org_unit_id, holder_member_id, encrypted_fields) "
    "VALUES ($1, $2, $3, $3, $4, $5, $6, $7::jsonb)"
)


def _token() -> str:
    return uuid.uuid4().hex[:12]


def _file_provider(tmp_path: Path) -> FileSecretsProvider:
    (tmp_path / "file.key").write_bytes(os.urandom(32))
    ctx = ProviderContext(env="test", pillar="secrets", base_dir=tmp_path)
    return FileSecretsProvider(ctx, tmp_path, encryption_key_file="file.key")


def _self_scoped_caller(organization_id: uuid.UUID, member_id: uuid.UUID) -> MemberContext:
    return MemberContext(
        member_id=str(member_id),
        organization_id=str(organization_id),
        grants=(
            RoleGrant(
                id="g-read",
                organization_id=str(organization_id),
                role_key="member",
                scope_type=ScopeType.ORGANIZATION,
            ),
            RoleGrant(
                id="g-sensitive",
                organization_id=str(organization_id),
                role_key="asset_manager",
                scope_type=ScopeType.SELF,
            ),
        ),
    )


async def test_a_self_scoped_read_sensitive_grant_only_decrypts_the_callers_own_held_asset(
    make_pool: PoolFactory, isolation_db: IsolationDb, tmp_path: Path
) -> None:
    pool = await make_pool("api")
    org = isolation_db.org_a
    provider = _file_provider(tmp_path)
    category_id, unit_id = uuid.uuid4(), uuid.uuid4()
    holder_id, other_member_id, asset_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    encrypted = await encrypt_custom_fields(
        provider, organization_id=str(org), plaintexts={"ssn": json.dumps("123-45-6789")}
    )
    async with tenant_transaction(pool, org) as conn:
        await conn.execute(INSERT_CATEGORY, category_id, org, _token())
        await conn.execute(INSERT_ORG_UNIT, unit_id, org, _token())
        await conn.execute(INSERT_MEMBER, holder_id, org, _token(), f"sub-{holder_id}")
        await conn.execute(INSERT_MEMBER, other_member_id, org, _token(), f"sub-{other_member_id}")
        await conn.execute(
            INSERT_ASSET, asset_id, org, _token(), category_id, unit_id, holder_id, json.dumps(encrypted)
        )

    # The holder: a self-scoped read_sensitive grant covers this asset (they hold it).
    holder_view = await get_asset(
        pool,
        organization_id=org,
        caller=_self_scoped_caller(org, holder_id),
        secrets_provider=provider,
        asset_id=asset_id,
    )
    assert holder_view.encrypted_fields.get("ssn") == "123-45-6789"

    # A different member with the same self-scoped grant: the asset is not theirs, so the grant
    # must not cover it -- presence only, never the plaintext.
    other_view = await get_asset(
        pool,
        organization_id=org,
        caller=_self_scoped_caller(org, other_member_id),
        secrets_provider=provider,
        asset_id=asset_id,
    )
    assert other_view.encrypted_fields.get("ssn") != "123-45-6789"
    assert "123-45-6789" not in json.dumps(other_view.encrypted_fields)
