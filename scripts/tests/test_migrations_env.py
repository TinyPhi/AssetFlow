# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""backend/migrations/env.py reads the migrator DSN from a file as well as the environment (AF-047).

The script runs Alembic when imported. Alembic and SQLAlchemy are replaced by small stand-ins and
the module is loaded in offline mode, so no database and no extra dependency is needed.

Run: make test-scripts
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from typing import Any, ClassVar, Self
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


# ------------------------------------------------------------- secret:// password resolution (AF-047)
# `resolved_migration_url`/`_resolve_secret_ref` import the app package lazily (see env.py's own
# comment); stand in for just the names they use, same spirit as the alembic/sqlalchemy stubs above.


class _FakeURL:
    """Enough of sqlalchemy.engine.URL for resolved_migration_url: .password, .set(), rendering.

    Parses by hand rather than with urllib.parse.urlsplit: a `secret://area/name#key` password
    contains `#` and `/`, which urlsplit reads as a URL fragment/path separator. SQLAlchemy's own
    make_url does not have this problem (verified against the real library); this stand-in must not
    introduce one that the real code doesn't have.
    """

    def __init__(self, raw: str) -> None:
        scheme, rest = raw.split("://", 1)
        # The database name is after the *last* slash: a secret:// password embeds its own slashes.
        creds_host, _, database = rest.rpartition("/")
        creds, _, host_port = creds_host.rpartition("@")
        user, _, password = creds.partition(":")
        host, _, port = host_port.partition(":")
        self._scheme, self._user, self._host, self._port, self._database = scheme, user, host, port, database
        self.password = password

    def set(self, *, password: str) -> _FakeURL:
        return _FakeURL(self._render(password))

    def render_as_string(self, hide_password: bool = False) -> str:
        return self._render(self.password)

    def _render(self, password: str) -> str:
        port = f":{self._port}" if self._port else ""
        return f"{self._scheme}://{self._user}:{password}@{self._host}{port}/{self._database}"


class _FakeOpenBaoSettings:
    def __init__(self, *, address: str, token: str) -> None:
        self.address = address
        self.token = token


class _FakeOpenBaoProvider:
    """Records every `get()` call; returns a canned value keyed by the reference."""

    calls: ClassVar[list[str]] = []
    values: ClassVar[dict[str, str]] = {}

    def __init__(self, settings: _FakeOpenBaoSettings, context: Any) -> None:
        self.settings = settings
        self.context = context

    async def get(self, ref: str) -> str:
        type(self).calls.append(ref)
        return type(self).values[ref]

    async def aclose(self) -> None:
        return None


@pytest.fixture
def app_stubs(monkeypatch: pytest.MonkeyPatch) -> Any:
    _FakeOpenBaoProvider.calls = []
    _FakeOpenBaoProvider.values = {}
    stubs = {
        "sqlalchemy.engine": types.SimpleNamespace(Connection=object, make_url=_FakeURL),
        "app": types.ModuleType("app"),
        "app.core": types.ModuleType("app.core"),
        "app.core.config": types.SimpleNamespace(is_secret_ref=lambda v: v.startswith("secret://")),
        "app.providers": types.ModuleType("app.providers"),
        "app.providers.context": types.SimpleNamespace(
            ProviderContext=lambda **kw: types.SimpleNamespace(**kw)
        ),
        "app.providers.secrets": types.ModuleType("app.providers.secrets"),
        "app.providers.secrets.openbao": types.SimpleNamespace(
            OpenBaoSecretsProvider=_FakeOpenBaoProvider, OpenBaoSettings=_FakeOpenBaoSettings
        ),
    }
    for name, module in stubs.items():
        monkeypatch.setitem(sys.modules, name, module)
    return _FakeOpenBaoProvider


def test_a_secret_ref_password_is_resolved_through_openbao(
    env_module: Any, app_stubs: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref = "secret://assetflow/postgres#superuser_password"
    app_stubs.values[ref] = "the-real-password"
    monkeypatch.setenv(URL_VAR, f"postgresql://postgres:{ref}@db.example.org:5432/assetflow")
    monkeypatch.setenv("BAO_TOKEN", "a-root-token")
    monkeypatch.setenv("BAO_ADDR", "http://openbao:8200")

    resolved = asyncio.run(env_module.resolved_migration_url())

    assert "the-real-password" in resolved
    assert ref not in resolved
    assert app_stubs.calls == [ref]


def test_a_secret_ref_password_without_bao_token_fails_clearly(
    env_module: Any, app_stubs: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref = "secret://assetflow/postgres#superuser_password"
    monkeypatch.setenv(URL_VAR, f"postgresql://postgres:{ref}@db.example.org:5432/assetflow")
    monkeypatch.delenv("BAO_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="BAO_TOKEN"):
        asyncio.run(env_module.resolved_migration_url())


def test_a_plain_password_is_never_sent_to_openbao(
    env_module: Any, app_stubs: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(URL_VAR, DSN)
    monkeypatch.setenv("BAO_TOKEN", "a-root-token")

    resolved = asyncio.run(env_module.resolved_migration_url())

    assert resolved == DSN.replace("postgresql://", "postgresql+asyncpg://", 1)
    assert app_stubs.calls == []
