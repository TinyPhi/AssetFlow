# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Organization isolation against a real PostgreSQL (§B5.2, §B10, §C4.8, §C8.5).

Every test connects as a LOGIN user that belongs to a group role (never the superuser) through
app.core.db, so RLS, grants and the transaction helpers are all exercised for real.
"""

from __future__ import annotations

import uuid

import asyncpg
import pytest
from pg_harness import IsolationDb, PoolFactory

from app.core.db import platform_transaction, tenant_transaction

RESOLVER = "platform.resolve_organization(text)"


# ---------------------------------------------------------------- unstamped connections


async def test_unstamped_api_connection_sees_no_organizations(make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    async with platform_transaction(pool) as conn:
        assert await conn.fetchval("SELECT count(*) FROM public.organizations") == 0
    async with pool.acquire() as conn:  # even without any helper
        assert await conn.fetchval("SELECT count(*) FROM public.organizations") == 0


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE public.organizations SET name = 'x'",
        "DELETE FROM public.organizations",
        "INSERT INTO public.organizations (id, slug, name, idp_organization_id, domain_key)"
        " VALUES (gen_random_uuid(), 'x', 'x', 'x', 'it')",
    ],
)
async def test_api_role_cannot_write_organizations(make_pool: PoolFactory, sql: str) -> None:
    pool = await make_pool("api")
    async with platform_transaction(pool) as conn:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute(sql)


async def test_unstamped_writes_affect_no_rows_even_for_the_table_owner(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    """The migrator owns the table; FORCE ROW LEVEL SECURITY still applies to it."""
    pool = await make_pool("migrator")
    async with platform_transaction(pool) as conn:
        assert await conn.fetchval("SELECT count(*) FROM public.organizations") == 0
        assert await conn.execute("UPDATE public.organizations SET name = 'x'") == "UPDATE 0"
        assert await conn.execute("DELETE FROM public.organizations") == "DELETE 0"
    async with platform_transaction(pool) as conn:
        with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
            await conn.execute(
                "INSERT INTO public.organizations (id, slug, name, idp_organization_id, domain_key)"
                " VALUES ($1, 'x', 'x', 'x', 'it')",
                uuid.uuid4(),
            )
    admin = await asyncpg.connect(isolation_db.admin_dsn)
    try:
        assert await admin.fetchval("SELECT count(*) FROM public.organizations WHERE name = 'x'") == 0
    finally:
        await admin.close()


# ---------------------------------------------------------------- stamped connections


async def test_org_a_context_sees_only_org_a(make_pool: PoolFactory, isolation_db: IsolationDb) -> None:
    pool = await make_pool("api")
    async with tenant_transaction(pool, isolation_db.org_a) as conn:
        rows = await conn.fetch("SELECT id FROM public.organizations")
        assert [r["id"] for r in rows] == [isolation_db.org_a]
        by_id = "SELECT count(*) FROM public.organizations WHERE id = $1"
        assert await conn.fetchval(by_id, isolation_db.org_b) == 0


async def test_org_a_context_cannot_write_org_b(make_pool: PoolFactory, isolation_db: IsolationDb) -> None:
    pool = await make_pool("migrator")  # the only role with write grants; RLS still applies
    a, b = isolation_db.org_a, isolation_db.org_b
    async with tenant_transaction(pool, a) as conn:
        assert await conn.execute("UPDATE public.organizations SET name = 'x' WHERE id = $1", b) == "UPDATE 0"
        assert await conn.execute("DELETE FROM public.organizations WHERE id = $1", b) == "DELETE 0"
    async with tenant_transaction(pool, a) as conn:
        with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
            await conn.execute(
                "INSERT INTO public.organizations (id, slug, name, idp_organization_id, domain_key)"
                " VALUES ($1, 'x', 'x', 'x', 'it')",
                uuid.uuid4(),
            )
    async with tenant_transaction(pool, a) as conn:
        with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
            await conn.execute("UPDATE public.organizations SET id = $2 WHERE id = $1", a, uuid.uuid4())
    async with tenant_transaction(pool, b) as conn:
        assert await conn.fetchval("SELECT name FROM public.organizations") == "Organization B"


async def test_context_does_not_leak_to_the_next_transaction(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    pool = await make_pool("api")  # one connection, so every block reuses the same backend
    async with tenant_transaction(pool, isolation_db.org_a) as conn:
        pid = await conn.fetchval("SELECT pg_backend_pid()")
        assert await conn.fetchval("SELECT count(*) FROM public.organizations") == 1
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT pg_backend_pid()") == pid
        assert not await conn.fetchval("SELECT current_setting('app.organization_id', true)")
        assert await conn.fetchval("SELECT count(*) FROM public.organizations") == 0

    with pytest.raises(RuntimeError, match="boom"):
        async with tenant_transaction(pool, isolation_db.org_a):
            raise RuntimeError("boom")
    async with platform_transaction(pool) as conn:
        assert await conn.fetchval("SELECT pg_backend_pid()") == pid
        assert await conn.fetchval("SELECT count(*) FROM public.organizations") == 0


async def test_context_does_not_leak_after_a_failed_statement(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    pool = await make_pool("api")
    with pytest.raises(asyncpg.DivisionByZeroError):
        async with tenant_transaction(pool, isolation_db.org_a) as conn:
            await conn.fetchval("SELECT 1 / 0")
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM public.organizations") == 0


async def test_tenant_transaction_refuses_a_non_uuid(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    pool = await make_pool("api")
    with pytest.raises(TypeError):
        async with tenant_transaction(pool, str(isolation_db.org_a)):  # type: ignore[arg-type]
            pytest.fail("the block must not run")


@pytest.mark.parametrize("behind_pgbouncer", [False, True])
async def test_timeouts_are_applied(
    make_pool: PoolFactory, isolation_db: IsolationDb, behind_pgbouncer: bool
) -> None:
    pool = await make_pool("api", behind_pgbouncer=behind_pgbouncer)
    async with tenant_transaction(pool, isolation_db.org_a) as conn:
        assert await conn.fetchval("SHOW statement_timeout") == "15s"
        assert await conn.fetchval("SHOW idle_in_transaction_session_timeout") == "30s"


# ---------------------------------------------------------------- the sign-in resolver


async def test_resolver_returns_only_id_and_status(make_pool: PoolFactory, isolation_db: IsolationDb) -> None:
    pool = await make_pool("api")
    async with platform_transaction(pool) as conn:
        rows = await conn.fetch("SELECT * FROM platform.resolve_organization($1)", isolation_db.idp_b)
        assert [dict(r) for r in rows] == [{"id": isolation_db.org_b, "status": "active"}]
        assert await conn.fetch("SELECT * FROM platform.resolve_organization($1)", "unknown-idp-org") == []
        assert await conn.fetch("SELECT * FROM platform.resolve_organization($1)", "%") == []
        # Still nothing readable from the table itself.
        assert await conn.fetchval("SELECT count(*) FROM public.organizations") == 0


@pytest.mark.parametrize("kind", ["worker", "readonly"])
async def test_resolver_is_refused_to_other_roles(
    make_pool: PoolFactory, isolation_db: IsolationDb, kind: str
) -> None:
    pool = await make_pool(kind)
    async with platform_transaction(pool) as conn:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.fetch("SELECT * FROM platform.resolve_organization($1)", isolation_db.idp_a)


async def test_resolver_privileges_and_definition(isolation_db: IsolationDb) -> None:
    admin = await asyncpg.connect(isolation_db.admin_dsn)
    try:
        others = ("public", "assetflow_worker", "assetflow_readonly", isolation_db.users["worker"].name)
        for grantee in others:
            assert not await admin.fetchval(
                "SELECT has_function_privilege($1, $2, 'EXECUTE')", grantee, RESOLVER
            ), grantee
        assert await admin.fetchval(
            "SELECT has_function_privilege($1, $2, 'EXECUTE')", isolation_db.users["api"].name, RESOLVER
        )
        fn = await admin.fetchrow(
            "SELECT p.prosecdef, p.proconfig, r.rolname AS owner, p.proacl::text[] AS acl"
            " FROM pg_proc p JOIN pg_roles r ON r.oid = p.proowner WHERE p.oid = $1::regprocedure",
            RESOLVER,
        )
        assert fn is not None
        assert fn["prosecdef"] is True
        assert fn["proconfig"] == ["search_path=pg_catalog, pg_temp"]
        assert fn["owner"] == "assetflow_resolver"
        grantees = sorted(entry.split("=", 1)[0] for entry in fn["acl"])
        assert grantees == ["assetflow_api", "assetflow_resolver"]
        owner = await admin.fetchrow(
            "SELECT rolsuper, rolbypassrls, rolcanlogin FROM pg_roles WHERE rolname = 'assetflow_resolver'"
        )
        assert owner is not None
        assert tuple(owner) == (False, False, False)
    finally:
        await admin.close()


# ---------------------------------------------------------------- roles and table settings


async def test_roles_have_no_superuser_or_bypassrls(isolation_db: IsolationDb) -> None:
    names = [
        "assetflow_api",
        "assetflow_worker",
        "assetflow_migrator",
        "assetflow_readonly",
        "assetflow_resolver",
        *(u.name for u in isolation_db.users.values()),
    ]
    admin = await asyncpg.connect(isolation_db.admin_dsn)
    try:
        rows = await admin.fetch(
            "SELECT rolname, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole FROM pg_roles"
            " WHERE rolname = ANY($1::text[])",
            names,
        )
        assert sorted(r["rolname"] for r in rows) == sorted(names)
        for r in rows:
            assert (r["rolsuper"], r["rolbypassrls"], r["rolcreatedb"], r["rolcreaterole"]) == (
                False,
                False,
                False,
                False,
            ), r["rolname"]
    finally:
        await admin.close()


async def test_organizations_table_forces_rls_and_is_not_owned_by_the_api(isolation_db: IsolationDb) -> None:
    admin = await asyncpg.connect(isolation_db.admin_dsn)
    try:
        table = await admin.fetchrow(
            "SELECT c.relrowsecurity, c.relforcerowsecurity, r.rolname AS owner FROM pg_class c"
            " JOIN pg_roles r ON r.oid = c.relowner WHERE c.oid = 'public.organizations'::regclass"
        )
        assert table is not None
        assert table["relrowsecurity"] is True
        assert table["relforcerowsecurity"] is True
        assert table["owner"] == "assetflow_migrator"
        for kind in ("api", "worker", "readonly"):
            user = isolation_db.users[kind].name
            member = await admin.fetchval("SELECT pg_has_role($1, $2, 'MEMBER')", user, table["owner"])
            assert not member, kind
    finally:
        await admin.close()


@pytest.mark.parametrize("kind", ["api", "worker", "readonly"])
async def test_app_roles_cannot_create_objects(make_pool: PoolFactory, kind: str) -> None:
    pool = await make_pool(kind)
    async with pool.acquire() as conn:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute("CREATE TABLE public.intruder (id int)")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute("CREATE FUNCTION platform.intruder() RETURNS int LANGUAGE sql AS 'SELECT 1'")


async def test_no_login_user_inherits_the_resolver_role(isolation_db: IsolationDb) -> None:
    """The resolver's USING (true) policy must reach nobody but the function owner."""
    admin = await asyncpg.connect(isolation_db.admin_dsn)
    try:
        for kind, user in isolation_db.users.items():
            usage = await admin.fetchval("SELECT pg_has_role($1, 'assetflow_resolver', 'USAGE')", user.name)
            assert not usage, kind
        inheriting = await admin.fetchval(
            "SELECT count(*) FROM pg_auth_members"
            " WHERE roleid = 'assetflow_resolver'::regrole AND inherit_option"
        )
        assert inheriting == 0
    finally:
        await admin.close()
