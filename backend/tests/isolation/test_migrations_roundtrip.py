# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Migrations upgrade, downgrade and upgrade again on a real PostgreSQL (§C5.4, M1.4-T1).

Roles are cluster-wide, so `downgrade base` drops them; this runs on the suite's own disposable
server and re-provisions the login users and fixture organizations afterwards.
"""

from __future__ import annotations

import asyncpg
from pg_harness import IsolationDb


async def _objects(db: IsolationDb) -> tuple[bool, bool, int]:
    conn = await asyncpg.connect(db.admin_dsn)
    try:
        table = await conn.fetchval("SELECT to_regclass('public.organizations') IS NOT NULL")
        fn = await conn.fetchval("SELECT to_regprocedure('platform.resolve_organization(text)') IS NOT NULL")
        roles = await conn.fetchval("SELECT count(*) FROM pg_roles WHERE rolname LIKE 'assetflow\\_%'")
        return bool(table), bool(fn), int(roles)
    finally:
        await conn.close()


async def _sql(db: IsolationDb, sql: str) -> None:
    conn = await asyncpg.connect(db.admin_dsn)
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


async def _release_roles_in_other_databases(db: IsolationDb) -> None:
    """Drop the AssetFlow roles' rights in every other database of the cluster.

    Roles are cluster-wide, and `DROP ROLE` fails while the role still holds a grant in any
    database. Another test session (or a leftover database) on the same server would block the
    `downgrade base` below, so its grants are released first. Only AssetFlow's own roles are touched.
    """
    admin = await asyncpg.connect(db.admin_dsn)
    try:
        names = [
            r["datname"]
            for r in await admin.fetch(
                "SELECT datname FROM pg_database WHERE NOT datistemplate AND datname <> current_database()"
            )
        ]
        roles = [
            r["rolname"]
            for r in await admin.fetch("SELECT rolname FROM pg_roles WHERE rolname LIKE 'assetflow%'")
        ]
    finally:
        await admin.close()
    for name in names:
        conn = await asyncpg.connect(db.admin_dsn.rsplit("/", 1)[0] + "/" + name)
        try:
            for role in roles:
                await conn.execute(f'DROP OWNED BY "{role}"')
        except asyncpg.PostgresError:
            pass  # a database we cannot enter or that is gone is not holding anything we can drop
        finally:
            await conn.close()


def _ok(result: object) -> None:
    rc = getattr(result, "returncode", None)
    assert rc == 0, f"{getattr(result, 'stdout', '')}\n{getattr(result, 'stderr', '')}"


async def test_upgrade_downgrade_upgrade(isolation_db: IsolationDb) -> None:
    db = isolation_db
    try:
        assert await _objects(db) == (True, True, 5)

        _ok(db.alembic("downgrade", "0000_roles"))
        assert await _objects(db) == (False, False, 5)

        await _release_roles_in_other_databases(db)
        _ok(db.alembic("downgrade", "base"))
        assert await _objects(db) == (False, False, 0)

        _ok(db.alembic("upgrade", "head"))
        assert await _objects(db) == (True, True, 5)
    finally:
        db.upgrade_head()
        await db.provision()


async def test_roles_migration_is_idempotent_and_refuses_unsafe_roles(isolation_db: IsolationDb) -> None:
    db = isolation_db
    try:
        await _release_roles_in_other_databases(db)
        _ok(db.alembic("downgrade", "base"))

        # A role left from an earlier install with safe attributes is reused.
        await _sql(db, "CREATE ROLE assetflow_api NOLOGIN")
        _ok(db.alembic("upgrade", "0000_roles"))
        _ok(db.alembic("downgrade", "base"))

        # A role with BYPASSRLS stops the migration.
        await _sql(db, "CREATE ROLE assetflow_api NOLOGIN BYPASSRLS")
        result = db.alembic("upgrade", "head")
        assert result.returncode != 0
        assert "unsafe attributes" in result.stderr
        assert await _objects(db) == (False, False, 1)
        await _sql(db, "DROP ROLE assetflow_api")
    finally:
        db.upgrade_head()
        await db.provision()
