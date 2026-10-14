# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Tenant isolation tests for notification channel installations (§B6.3, §C8.5)."""

from __future__ import annotations

import uuid

import asyncpg
import pytest
from pg_harness import IsolationDb, PoolFactory
from tenant_checks import assert_tenant_isolation, token

from app.core.db import tenant_transaction

INSERT = (
    "INSERT INTO public.notification_channels (id, organization_id, channel_key, display_name) "
    "VALUES ($1, $2, $3, 'Test channel')"
)


async def test_notification_channels_api_tenant_isolation(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    # The admin API installs and configures channels but never deletes a row: "uninstall" is
    # enabled=false (the kill switch), not a DELETE, so the api role has no DELETE grant here.
    await assert_tenant_isolation(
        make_pool,
        isolation_db,
        "notification_channels",
        INSERT,
        update_column="channel_key",
        can_delete=False,
    )


async def test_worker_can_read_and_install_but_not_update_or_delete_notification_channels(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    """P6-03 grants the worker INSERT too (0011), so it can auto-install `inapp` on first use
    (§B6.3: it needs no admin setup) - but never UPDATE or DELETE an installation row; that stays
    the admin API's job."""
    api = await make_pool("api")
    row_id = uuid.uuid4()
    async with tenant_transaction(api, isolation_db.org_a) as conn:
        await conn.execute(INSERT, row_id, isolation_db.org_a, token())

    worker = await make_pool("worker")
    async with tenant_transaction(worker, isolation_db.org_a) as conn:
        found = await conn.fetchval(
            "SELECT channel_key FROM public.notification_channels WHERE id = $1", row_id
        )
        assert found is not None
        with pytest.raises(asyncpg.InsufficientPrivilegeError, match="permission denied"):
            async with conn.transaction():
                await conn.execute(
                    "UPDATE public.notification_channels SET channel_key = channel_key WHERE id = $1",
                    row_id,
                )
        with pytest.raises(asyncpg.InsufficientPrivilegeError, match="permission denied"):
            async with conn.transaction():
                await conn.execute("DELETE FROM public.notification_channels WHERE id = $1", row_id)
        installed_id = uuid.uuid4()
        await conn.execute(INSERT, installed_id, isolation_db.org_a, token())
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM public.notification_channels WHERE id = $1", installed_id
            )
            == 1
        )
