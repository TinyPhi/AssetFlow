# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""backend/migrations/env.py reads the migrator DSN from a file as well as the environment (AF-047).

The script runs Alembic when imported. Alembic and SQLAlchemy are replaced by small stand-ins and
the module is loaded in offline mode, so no database and no extra dependency is needed.

Run: make test-scripts
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any, Self
from urllib.parse import urlsplit

import pytest

ENV_PY = Path(__file__).resolve().parent.parent.parent / "backend" / "migrations" / "env.py"
URL_VAR = "ASSETFLOW_MIGRATION_DATABASE_URL"
FILE_VAR = "ASSETFLOW_MIGRATION_DATABASE_URL_FILE"
# A made-up DSN with a made-up password, for these tests only.
DSN = "postgresql://migrator:not-a-real-password@db.example.org:5432/assetflow"


class _Context:
    config = types.SimpleNamespace(config_file_name=None)

    def is_offline_mode(self) -> bool:
        return True

    def configure(self, **_kwargs: Any) -> None:
        return None

    def run_migrations(self) -> None:
        return None


class _Transaction:
    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False


@pytest.fixture
def env_module(monkeypatch: pytest.MonkeyPatch) -> Any:
    context = _Context()
    context.begin_transaction = lambda: _Transaction()  # type: ignore[method-assign]
    stubs = {
        "alembic": types.SimpleNamespace(context=context),
        "alembic.context": context,
        "sqlalchemy": types.SimpleNamespace(pool=types.SimpleNamespace(NullPool=object)),
        "sqlalchemy.engine": types.SimpleNamespace(Connection=object),
        "sqlalchemy.ext": types.ModuleType("sqlalchemy.ext"),
        "sqlalchemy.ext.asyncio": types.SimpleNamespace(create_async_engine=lambda *a, **k: None),
    }
    for name, module in stubs.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.delenv(URL_VAR, raising=False)
    monkeypatch.delenv(FILE_VAR, raising=False)
    spec = importlib.util.spec_from_file_location("assetflow_migrations_env", ENV_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_dsn_is_read_from_a_file(
    env_module: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    secret = tmp_path / "migrator_dsn"
    secret.write_text(DSN + "\n", encoding="utf-8")
    monkeypatch.setenv(FILE_VAR, str(secret))
    assert env_module.migration_url() == DSN.replace("postgresql://", "postgresql+asyncpg://", 1)


def test_the_file_wins_over_the_plain_variable(
    env_module: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    secret = tmp_path / "migrator_dsn"
    secret.write_text(DSN, encoding="utf-8")
    monkeypatch.setenv(FILE_VAR, str(secret))
    monkeypatch.setenv(URL_VAR, "postgresql://other:x@elsewhere.example.org/db")
    assert urlsplit(env_module.migration_url()).hostname == "db.example.org"


def test_the_plain_variable_still_works(env_module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(URL_VAR, DSN)
    assert env_module.migration_url().startswith("postgresql+asyncpg://migrator:")


def test_neither_variable_set_names_both(env_module: Any) -> None:
    with pytest.raises(RuntimeError) as excinfo:
        env_module.migration_url()
    assert FILE_VAR in str(excinfo.value) and URL_VAR in str(excinfo.value)


def test_an_unreadable_or_empty_file_fails_without_leaking(
    env_module: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(FILE_VAR, str(tmp_path / "missing"))
    with pytest.raises(RuntimeError, match="cannot be read"):
        env_module.migration_url()
    empty = tmp_path / "empty"
    empty.write_text("  \n", encoding="utf-8")
    monkeypatch.setenv(FILE_VAR, str(empty))
    with pytest.raises(RuntimeError, match="is empty"):
        env_module.migration_url()


def test_a_wrong_scheme_error_does_not_echo_the_dsn(
    env_module: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    secret = tmp_path / "dsn"
    secret.write_text("mysql://migrator:not-a-real-password@db.example.org/x", encoding="utf-8")
    monkeypatch.setenv(FILE_VAR, str(secret))
    with pytest.raises(RuntimeError) as excinfo:
        env_module.migration_url()
    assert "not-a-real-password" not in str(excinfo.value)
