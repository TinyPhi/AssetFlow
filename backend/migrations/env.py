# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Alembic environment for AssetFlow's raw-SQL migrations (§B10, §C4.8, D6).

Online migrations connect with the asyncpg driver (SQLAlchemy `postgresql+asyncpg`) using the
migrator DSN from ASSETFLOW_MIGRATION_DATABASE_URL_FILE (a path to a file holding the DSN, so the
password need not sit in the process environment) or, when that is unset, from
ASSETFLOW_MIGRATION_DATABASE_URL. There is no default: the DSN carries the migrator's credentials,
which come from the secrets provider or the operator, never from code.
Offline mode (`alembic upgrade head --sql`) needs no database and no DSN.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

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
        migration_url(),
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
