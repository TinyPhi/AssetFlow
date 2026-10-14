# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Alembic environment for AssetFlow's raw-SQL migrations (§B10, §C4.8, D6).

Online migrations connect with the asyncpg driver (SQLAlchemy `postgresql+asyncpg`) using the
migrator DSN from ASSETFLOW_MIGRATION_DATABASE_URL_FILE (a path to a file holding the DSN, so the
password need not sit in the process environment) or, when that is unset, from
ASSETFLOW_MIGRATION_DATABASE_URL. There is no default: the DSN carries the migrator's credentials,
which come from the secrets provider or the operator, never from code. The DSN's password may
itself be a `secret://<area>/<name>#<key>` reference (AF-047): resolved through OpenBao using
BAO_ADDR/BAO_TOKEN from the environment, so the real password is never written to a file or env
var at all, only the reference is.
Offline mode (`alembic upgrade head --sql`) needs no database and no DSN.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig
from pathlib import Path
from typing import TYPE_CHECKING

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

if TYPE_CHECKING:
    # Only for the type checker: a plain local-variable annotation is never evaluated at runtime
    # (even with `from __future__ import annotations`), so this costs nothing at import time and
    # keeps this script's only hard dependencies alembic and sqlalchemy.
    from app.core.config import Environment

MIGRATION_URL_ENV = "ASSETFLOW_MIGRATION_DATABASE_URL"
MIGRATION_URL_FILE_ENV = f"{MIGRATION_URL_ENV}_FILE"

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def _raw_url() -> str:
    """The DSN text: the file named by ..._FILE when set (it wins), else the plain variable."""
    file_name = os.environ.get(MIGRATION_URL_FILE_ENV, "").strip()
    if file_name:
        try:
            url = Path(file_name).read_text(encoding="utf-8").strip()
        except OSError as exc:
            # Name only the file, never its content.
            reason = exc.strerror
            raise RuntimeError(f"{MIGRATION_URL_FILE_ENV}={file_name} cannot be read: {reason}") from exc
        if not url:
            raise RuntimeError(f"{MIGRATION_URL_FILE_ENV}={file_name} is empty")
        return url
    return os.environ.get(MIGRATION_URL_ENV, "").strip()


def migration_url() -> str:
    """The migrator DSN as a SQLAlchemy asyncpg URL; fails when neither variable is set."""
    url = _raw_url()
    if not url:
        raise RuntimeError(
            f"{MIGRATION_URL_FILE_ENV} (a file holding the DSN) or {MIGRATION_URL_ENV} is not set. "
            "Set one to the migrator's DSN, "
            "e.g. postgresql://<migrator user>:<password>@<host>:5432/<database>."
        )
    for prefix in ("postgresql+asyncpg://", "postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url[len(prefix) :]
    raise RuntimeError("the migrator DSN must be a postgresql:// URL")


async def _resolve_secret_ref(ref: str) -> str:
    """Resolve a `secret://<area>/<name>#<key>` DSN password through OpenBao (AF-047).

    Deliberately narrow: this exists only so a caller can pass a reference instead of ever writing
    the real password to disk, not to support every configured secrets provider. BAO_ADDR/BAO_TOKEN
    must already be set in the environment (the caller's own responsibility, for the one process
    that needs them). Imports the app package lazily: this script is also exercised standalone, in
    offline mode, by scripts/tests/test_migrations_env.py, which stubs only alembic and sqlalchemy
    and must not need the full app package (pydantic, httpx, ...) just to import this file.
    """
    from app.providers.context import ProviderContext  # noqa: PLC0415
    from app.providers.secrets.openbao import OpenBaoSecretsProvider, OpenBaoSettings  # noqa: PLC0415

    token = os.environ.get("BAO_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BAO_TOKEN must be set in the environment to resolve a secret:// DSN password")
    settings = OpenBaoSettings(address=os.environ.get("BAO_ADDR", "http://localhost:19200"), token=token)
    raw_env = os.environ.get("ASSETFLOW_ENV", "development")
    env: Environment = "development"
    if raw_env in ("test", "staging", "production"):
        env = raw_env  # type: ignore[assignment]
    provider_context = ProviderContext(env=env, pillar="secrets", base_dir=Path.cwd())
    provider = OpenBaoSecretsProvider(settings, provider_context)
    try:
        return await provider.get(ref)
    finally:
        await provider.aclose()


async def resolved_migration_url() -> str:
    """`migration_url()`'s DSN, with a `secret://...` password resolved through OpenBao."""
    from sqlalchemy.engine import make_url  # noqa: PLC0415

    from app.core.config import is_secret_ref  # noqa: PLC0415

    url = make_url(migration_url())
    if url.password and is_secret_ref(url.password):
        url = url.set(password=await _resolve_secret_ref(url.password))
    return url.render_as_string(hide_password=False)


def run_migrations_offline() -> None:
    context.configure(
        dialect_name="postgresql",
        target_metadata=target_metadata,
        literal_binds=True,
        transactional_ddl=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_sync(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, transactional_ddl=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(
        await resolved_migration_url(),
        poolclass=pool.NullPool,
        connect_args={
            "server_settings": {
                "application_name": "assetflow-migrator",
                # Fail fast instead of queueing behind long-running application transactions.
                "lock_timeout": "10s",
            }
        },
    )
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run_sync)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
