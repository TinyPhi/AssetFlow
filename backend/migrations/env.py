# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Alembic environment for AssetFlow's raw-SQL migrations (§B10, §C4.8, D6).

Online migrations connect with the asyncpg driver (SQLAlchemy `postgresql+asyncpg`) using the
migrator DSN from ASSETFLOW_MIGRATION_DATABASE_URL. There is no default: the DSN carries the
migrator's credentials, which come from the secrets provider or the operator, never from code.
Offline mode (`alembic upgrade head --sql`) needs no database and no DSN.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

MIGRATION_URL_ENV = "ASSETFLOW_MIGRATION_DATABASE_URL"

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def migration_url() -> str:
    """The migrator DSN as a SQLAlchemy asyncpg URL; fails when the variable is unset."""
    url = os.environ.get(MIGRATION_URL_ENV, "").strip()
    if not url:
        raise RuntimeError(
            f"{MIGRATION_URL_ENV} is not set. Set it to the migrator's DSN, "
            "e.g. postgresql://<migrator user>:<password>@<host>:5432/<database>."
        )
    for prefix in ("postgresql+asyncpg://", "postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url[len(prefix) :]
    raise RuntimeError(f"{MIGRATION_URL_ENV} must be a postgresql:// URL")


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
