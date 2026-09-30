# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""A real PostgreSQL for the isolation suite: harness and fixtures (§C5.4, §C8.5).

Where the server comes from, in order:
  1. ASSETFLOW_TEST_DATABASE_URL: a superuser DSN of a disposable server (CI);
  2. in GitHub Actions only, ASSETFLOW_DATABASE_URL (the CI `postgres` service, trust auth);
  3. otherwise a throwaway `postgres:16-alpine` container started with the docker CLI on a random
     local port, with a superuser password generated for this run.
If none is available the suite is skipped with the reason; in CI it fails instead.

Each session creates its own database, migrates it with Alembic (`upgrade head`) and creates LOGIN
users with random passwords, one per group role: `api`, `worker`, `readonly`, `migrator`.
Organizations A and B are inserted by the superuser (which bypasses RLS) as fixture data.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import shutil
import subprocess
import sys
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, urlsplit

import asyncpg
import pytest

from app.core.db import DbRole, Pool, close_pool, init_pool

BACKEND_DIR = Path(__file__).resolve().parents[2]
POSTGRES_IMAGE = "postgres:16-alpine@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea"
LOGIN_ROLES = {
    "api": "assetflow_api",
    "worker": "assetflow_worker",
    "readonly": "assetflow_readonly",
    "migrator": "assetflow_migrator",
}
READY_TIMEOUT_S = 90.0


@dataclass(frozen=True)
class LoginUser:
    name: str
    password: str


@dataclass
class PgServer:
    """A PostgreSQL server reachable with a superuser DSN."""

    host: str
    port: int
    superuser: str
    superuser_password: str | None
    container_id: str | None = None

    def dsn(self, database: str, user: str | None = None, password: str | None = None) -> str:
        user = user or self.superuser
        password = password if user != self.superuser else self.superuser_password
        auth = quote(user, safe="") + (f":{quote(password, safe='')}" if password else "")
        return f"postgresql://{auth}@{self.host}:{self.port}/{quote(database, safe='')}"


@dataclass
class IsolationDb:
    """The migrated test database, its login users and the two fixture organizations."""

    server: PgServer
    database: str
    users: dict[str, LoginUser]
    org_a: uuid.UUID = field(default_factory=uuid.uuid4)
    org_b: uuid.UUID = field(default_factory=uuid.uuid4)
    idp_a: str = field(default_factory=lambda: f"idp-a-{secrets.token_hex(4)}")
    idp_b: str = field(default_factory=lambda: f"idp-b-{secrets.token_hex(4)}")

    @property
    def admin_dsn(self) -> str:
        return self.server.dsn(self.database)

    def alembic(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Run Alembic as the migrator (here the superuser, since roles are created by 0000)."""
        env = {**os.environ, "ASSETFLOW_MIGRATION_DATABASE_URL": self.admin_dsn}
        return subprocess.run(  # noqa: S603 - fixed argv, no shell
            [sys.executable, "-m", "alembic", "-c", str(BACKEND_DIR / "alembic.ini"), *args],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

    def upgrade_head(self) -> None:
        result = self.alembic("upgrade", "head")
        if result.returncode != 0:
            raise RuntimeError(f"alembic upgrade head failed:\n{result.stdout}\n{result.stderr}")

    async def provision(self) -> None:
        """Create or re-attach the login users and (re)insert organizations A and B. Idempotent."""
        conn = await asyncpg.connect(self.admin_dsn)
        try:
            for kind, user in self.users.items():
                exists = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", user.name)
                ident = _ident(user.name)
                if not exists:
                    await conn.execute(f"CREATE ROLE {ident} LOGIN PASSWORD {_literal(user.password)}")
                await conn.execute(f"GRANT {LOGIN_ROLES[kind]} TO {ident}")
            await conn.execute(
                """
                INSERT INTO public.organizations (id, slug, name, idp_organization_id, domain_key)
                VALUES ($1, 'org-a', 'Organization A', $2, 'it'),
                       ($3, 'org-b', 'Organization B', $4, 'rail')
                ON CONFLICT (id) DO NOTHING
                """,
                self.org_a,
                self.idp_a,
                self.org_b,
                self.idp_b,
            )
        finally:
            await conn.close()


def _ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _in_ci() -> bool:
    return os.environ.get("CI", "").lower() == "true" or os.environ.get("GITHUB_ACTIONS") == "true"


def _unavailable(reason: str) -> None:
    if _in_ci():
        pytest.fail(f"isolation suite needs PostgreSQL in CI: {reason}")
    pytest.skip(f"isolation suite skipped: {reason}")


def _server_from_url(url: str) -> PgServer:
    parts = urlsplit(url)
    if parts.scheme not in {"postgresql", "postgres"} or not parts.hostname:
        raise ValueError("the test database URL must be postgresql://user[:password]@host[:port]/db")
    return PgServer(
        host=parts.hostname,
        port=parts.port or 5432,
        superuser=parts.username or "postgres",
        superuser_password=parts.password,
    )


def _start_container(docker: str) -> PgServer:
    password = secrets.token_urlsafe(24)
    run = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [
            docker,
            "run",
            "--detach",
            "--rm",
            "--env",
            f"POSTGRES_PASSWORD={password}",
            "--publish",
            "127.0.0.1::5432",
            POSTGRES_IMAGE,
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if run.returncode != 0:
        _unavailable(f"docker run failed: {run.stderr.strip()[:300]}")
    container_id = run.stdout.strip()
    port_out = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [docker, "port", container_id, "5432/tcp"],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    port = int(port_out.stdout.strip().splitlines()[0].rsplit(":", 1)[1])
    return PgServer("127.0.0.1", port, "postgres", password, container_id)


async def _wait_ready(server: PgServer) -> None:
    deadline = time.monotonic() + READY_TIMEOUT_S
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            conn = await asyncpg.connect(server.dsn("postgres"), timeout=5)
        except (TimeoutError, OSError, asyncpg.PostgresError) as exc:
            last = exc
            await asyncio.sleep(0.5)
            continue
        try:
            await conn.fetchval("SELECT 1")
        finally:
            await conn.close()
        return
    raise RuntimeError(f"PostgreSQL did not become ready in {READY_TIMEOUT_S}s: {last!r}")


async def _admin(server: PgServer, sql: str) -> None:
    conn = await asyncpg.connect(server.dsn("postgres"))
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def pg_server() -> Iterator[PgServer]:
    url = os.environ.get("ASSETFLOW_TEST_DATABASE_URL", "").strip()
    if not url and os.environ.get("GITHUB_ACTIONS") == "true":
        url = os.environ.get("ASSETFLOW_DATABASE_URL", "").strip()
    if url:
        server = _server_from_url(url)
        asyncio.run(_wait_ready(server))
        yield server
        return

    docker = shutil.which("docker")
    if docker is None:
        _unavailable("set ASSETFLOW_TEST_DATABASE_URL or install Docker")
    assert docker is not None
    info = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [docker, "info", "--format", "{{.ServerVersion}}"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if info.returncode != 0:
        _unavailable("the Docker daemon is not reachable and ASSETFLOW_TEST_DATABASE_URL is not set")
    server = _start_container(docker)
    try:
        asyncio.run(_wait_ready(server))
        yield server
    finally:
        subprocess.run(  # noqa: S603 - fixed argv, no shell
            [docker, "rm", "--force", "--volumes", server.container_id or ""],
            capture_output=True,
            timeout=60,
            check=False,
        )


@pytest.fixture(scope="session")
def isolation_db(pg_server: PgServer) -> Iterator[IsolationDb]:
    suffix = secrets.token_hex(4)
    db = IsolationDb(
        server=pg_server,
        database=f"af_isolation_{suffix}",
        users={
            kind: LoginUser(f"af_test_{kind}_{suffix}", secrets.token_urlsafe(24)) for kind in LOGIN_ROLES
        },
    )
    asyncio.run(_admin(pg_server, f"CREATE DATABASE {_ident(db.database)}"))
    try:
        db.upgrade_head()
        asyncio.run(db.provision())
        yield db
    finally:
        asyncio.run(_admin(pg_server, f"DROP DATABASE IF EXISTS {_ident(db.database)} WITH (FORCE)"))
        for user in db.users.values():
            asyncio.run(_admin(pg_server, f"DROP ROLE IF EXISTS {_ident(user.name)}"))


@dataclass(frozen=True)
class _Role:
    user: str
    password: str


@dataclass(frozen=True)
class _DbCfg:
    """Implements app.core.db.DatabaseSettings for the tests (the real one is DatabaseConfig)."""

    host: str
    port: int
    name: str
    api: _Role
    worker: _Role
    migrator: _Role
    behind_pgbouncer: bool = False
    statement_timeout_ms: int = 15000
    idle_in_transaction_timeout_ms: int = 30000
    pool_min: int = 1
    pool_max: int = 1


PoolFactory = Callable[..., Awaitable[Pool]]
_SLOTS: dict[str, DbRole] = {"api": "api", "worker": "worker", "readonly": "worker", "migrator": "migrator"}


@pytest.fixture
async def make_pool(isolation_db: IsolationDb) -> AsyncIterator[PoolFactory]:
    """Open pools through app.core.db.init_pool, with passwords given as secret:// references."""
    secrets_by_ref = {f"secret://test/database#{k}": u.password for k, u in isolation_db.users.items()}
    pools: list[Pool] = []

    async def resolve_secret(ref: str) -> str:
        return secrets_by_ref[ref]

    def role(kind: str) -> _Role:
        return _Role(isolation_db.users[kind].name, f"secret://test/database#{kind}")

    async def factory(kind: str = "api", *, behind_pgbouncer: bool = False) -> Pool:
        # "readonly" connects through the worker slot: init_pool knows api, worker and migrator only.
        slot = _SLOTS[kind]
        cfg = _DbCfg(
            host=isolation_db.server.host,
            port=isolation_db.server.port,
            name=isolation_db.database,
            api=role("api"),
            worker=role("readonly" if kind == "readonly" else "worker"),
            migrator=role("migrator"),
            behind_pgbouncer=behind_pgbouncer,
        )
        pool = await init_pool(cfg, slot, resolve_secret)
        pools.append(pool)
        return pool

    yield factory
    for pool in pools:
        await close_pool(pool)
