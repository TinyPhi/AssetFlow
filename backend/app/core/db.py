# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Database pools and the organization-context transaction helpers (§B10, §C4.8, §B13.2).

Every query against tenant data runs inside `tenant_transaction`, which stamps the transaction with
`SELECT set_config('app.organization_id', $1, true)`. The setting is transaction-local, so PostgreSQL
drops it on COMMIT or ROLLBACK and it can never leak to the next user of a pooled connection. RLS
policies compare against it, so a connection without it sees no rows (fail closed).

Each process connects as one of the login users that belong to the group roles created by the first
migration (`assetflow_api`, `assetflow_worker`, `assetflow_migrator`). None of them is a superuser or
has BYPASSRLS; the API and worker roles do not own any table.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

import asyncpg
from asyncpg.pool import PoolConnectionProxy

DbRole = Literal["api", "worker", "migrator"]
SecretResolver = Callable[[str], Awaitable[str]]
# Lazily evaluated aliases: asyncpg's classes are generic only in asyncpg-stubs, not at runtime.
type Pool = asyncpg.Pool[asyncpg.Record]
type Connection = PoolConnectionProxy[asyncpg.Record]
type DirectConnection = asyncpg.Connection[asyncpg.Record]

SECRET_REF_PREFIX = "secret://"  # noqa: S105 - a URI scheme, not a password


class DbRoleSettings(Protocol):
    """One connection role (`database.api`, `database.worker`, `database.migrator`)."""

    @property
    def user(self) -> str: ...

    @property
    def password(self) -> str: ...


class DatabaseSettings(Protocol):
    """The fields of `app.core.config.DatabaseConfig` this module reads."""

    @property
    def host(self) -> str: ...

    @property
    def port(self) -> int: ...

    @property
    def name(self) -> str: ...

    @property
    def api(self) -> DbRoleSettings: ...

    @property
    def worker(self) -> DbRoleSettings: ...

    @property
    def migrator(self) -> DbRoleSettings: ...

    @property
    def behind_pgbouncer(self) -> bool: ...

    @property
    def statement_timeout_ms(self) -> int: ...

    @property
    def idle_in_transaction_timeout_ms(self) -> int: ...

    @property
    def pool_min(self) -> int: ...

    @property
    def pool_max(self) -> int: ...


@dataclass(frozen=True)
class _TransactionSettings:
    """Timeouts applied with SET LOCAL in each transaction (used behind PgBouncer, §B13.2)."""

    statement_timeout_ms: int
    idle_in_transaction_timeout_ms: int


# Pools created by init_pool that need per-transaction settings, keyed by id(pool). The pool object is
# kept in the value and compared by identity, so a reused id can never pick up another pool's settings.
_PER_TRANSACTION: dict[int, tuple[Pool, _TransactionSettings]] = {}
_DEFAULT_POOL_CONTAINER: dict[str, Pool | None] = {"pool": None}


def get_db_pool() -> Pool | None:
    """Return the global default database pool, or None if not set."""
    return _DEFAULT_POOL_CONTAINER["pool"]


def set_db_pool(pool: Pool | None) -> None:
    """Set the global default database pool."""
    _DEFAULT_POOL_CONTAINER["pool"] = pool


def _role_settings(cfg: DatabaseSettings, role: DbRole) -> DbRoleSettings:
    if role == "api":
        return cfg.api
    if role == "worker":
        return cfg.worker
    if role == "migrator":
        return cfg.migrator
    raise ValueError(f"unknown database role {role!r}")


async def _resolve_password(value: str, role: DbRole, resolve_secret: SecretResolver) -> str:
    """Resolve `secret://` references; a literal is accepted only because config validation already
    refuses literals outside development and test (§C1.6). An empty password is refused."""
    password = await resolve_secret(value) if value.startswith(SECRET_REF_PREFIX) else value
    if not password:
        raise ValueError(f"database.{role}.password resolved to an empty value")
    return password


async def init_pool(cfg: DatabaseSettings, role: DbRole, resolve_secret: SecretResolver) -> Pool:
    """Create an asyncpg pool for one connection role.

    Direct connections get `statement_timeout` and `idle_in_transaction_session_timeout` as session
    settings. Behind PgBouncer in transaction mode, session settings and prepared statements do not
    survive between transactions, so statement caching is turned off and the timeouts are applied
    with SET LOCAL by the transaction helpers instead.
    """
    role_cfg = _role_settings(cfg, role)
    password = await _resolve_password(role_cfg.password, role, resolve_secret)
    server_settings = {"application_name": f"assetflow-{role}"}
    if not cfg.behind_pgbouncer:
        server_settings["statement_timeout"] = str(cfg.statement_timeout_ms)
        server_settings["idle_in_transaction_session_timeout"] = str(cfg.idle_in_transaction_timeout_ms)
    pool = await asyncpg.create_pool(
        host=cfg.host,
        port=cfg.port,
        database=cfg.name,
        user=role_cfg.user,
        password=password,
        min_size=cfg.pool_min,
        max_size=cfg.pool_max,
        statement_cache_size=0 if cfg.behind_pgbouncer else 100,
        server_settings=server_settings,
    )
    if cfg.behind_pgbouncer:
        _PER_TRANSACTION[id(pool)] = (
            pool,
            _TransactionSettings(cfg.statement_timeout_ms, cfg.idle_in_transaction_timeout_ms),
        )
    return pool


async def close_pool(pool: Pool) -> None:
    """Close a pool created by init_pool (waits for connections to be released)."""
    entry = _PER_TRANSACTION.get(id(pool))
    if entry is not None and entry[0] is pool:
        del _PER_TRANSACTION[id(pool)]
    await pool.close()


async def _apply_transaction_settings(pool: Pool, conn: Connection, organization_id: str) -> None:
    entry = _PER_TRANSACTION.get(id(pool))
    if entry is not None and entry[0] is pool:
        settings = entry[1]
        await conn.execute(
            "SELECT set_config('app.organization_id', $1, true),"
            " set_config('statement_timeout', $2, true),"
            " set_config('idle_in_transaction_session_timeout', $3, true)",
            organization_id,
            str(settings.statement_timeout_ms),
            str(settings.idle_in_transaction_timeout_ms),
        )
    else:
        await conn.execute("SELECT set_config('app.organization_id', $1, true)", organization_id)


async def connect_direct(
    cfg: DatabaseSettings,
    role: DbRole,
    resolve_secret: SecretResolver,
    *,
    host: str | None = None,
    port: int | None = None,
) -> DirectConnection:
    """Open one dedicated connection (for LISTEN), bypassing PgBouncer when `host`/`port` are given."""
    role_cfg = _role_settings(cfg, role)
    password = await _resolve_password(role_cfg.password, role, resolve_secret)
    return await asyncpg.connect(
        host=host or cfg.host,
        port=port or cfg.port,
        database=cfg.name,
        user=role_cfg.user,
        password=password,
        server_settings={"application_name": f"assetflow-{role}-listen"},
    )


async def resolve_role_password(cfg: DatabaseSettings, role: DbRole, resolve_secret: SecretResolver) -> str:
    """Resolve one role's password without opening a connection.

    For a child process that must open its own connection (the job runner's memory-limited jobs,
    §B9.3): the parent resolves the password once and passes the plain value to the child, since an
    async secret resolver callable cannot be sent across a process boundary.
    """
    return await _resolve_password(_role_settings(cfg, role).password, role, resolve_secret)


@asynccontextmanager
async def tenant_transaction(pool: Pool, organization_id: UUID) -> AsyncGenerator[Connection]:
    """Run a block in one transaction stamped with the organization context.

    The context is transaction-local (`set_config(..., true)`), so PostgreSQL resets it when the
    transaction commits or rolls back; there is nothing to clean up afterwards.
    """
    if not isinstance(organization_id, UUID):
        raise TypeError(f"organization_id must be a UUID, not {type(organization_id).__name__}")
    async with pool.acquire() as conn, conn.transaction():
        await _apply_transaction_settings(pool, conn, str(organization_id))
        yield conn


@asynccontextmanager
async def worker_context(pool: Pool, organization_id: UUID) -> AsyncGenerator[Connection]:
    """Run worker code for one organization in one transaction (§B9.3, §C5.4 rule 3).

    Same stamp as `tenant_transaction`; the name marks the call site as a worker job. Every item a
    worker handles runs under the organization that owns it, so RLS applies exactly as for the API.
    """
    async with tenant_transaction(pool, organization_id) as conn:
        yield conn


@asynccontextmanager
async def worker_claim_transaction(pool: Pool) -> AsyncGenerator[Connection]:
    """Run the worker's cross-organization queue claim in one short transaction (§B9.3).

    No organization is set. Only `outbox` has worker claim policies, so every other tenant table
    reads as empty here; use it for claiming and recording results on `outbox` and nothing else.
    """
    async with platform_transaction(pool) as conn:
        yield conn


@asynccontextmanager
async def platform_transaction(pool: Pool) -> AsyncGenerator[Connection]:
    """Run a block in one transaction without an organization context.

    Only platform functions (such as `platform.resolve_organization`) return anything here; every
    RLS-protected table reads as empty. The context is explicitly cleared for this transaction so a
    session-level value set outside these helpers cannot apply.
    """
    async with pool.acquire() as conn, conn.transaction():
        await _apply_transaction_settings(pool, conn, "")
        yield conn
