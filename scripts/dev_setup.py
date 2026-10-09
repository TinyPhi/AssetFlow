#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""af-setup: the one-shot setup job of the local development stack (`make dev`).

Runs inside the backend image as `docker compose run --rm setup <step>` (deploy/compose.dev.yml) and
is removed afterwards. Steps, in the order scripts/dev.sh calls them:

openbao   Initialize OpenBao on its first start and unseal it with the local dev key (kept in the
          Docker volume assetflow_openbao_dev_keys, mounted only here), then run
          scripts/openbao-apply.py (engines, transit key `assetflow-fields` with derived keys,
          policies, AppRoles, fresh secret ids) and generate every missing credential into
          OpenBao. Only the bootstrap values that PostgreSQL and Zitadel need at first start are
          copied into the volume assetflow_runtime_secrets, plus each service's AppRole login.
zitadel   Run scripts/bootstrap_zitadel.py (project, apps, roles; client secrets go to OpenBao),
          then render the config file of api and worker into the runtime volume.
migrate   Alembic `upgrade head`, then the database login roles (passwords from OpenBao) and the
          assetflow_test database used by the test harness.
signin    Check that the first admin can open a Zitadel session (scripts/dev_signin_check.py).
admin-password
          A no-op that just points the caller at `make dev-admin-password` (scripts/dev.sh reads the
          password live from OpenBao itself, without going through this script).

OpenBao is the source of truth for every credential. Nothing is printed except step names, paths
and the names of what changed. The OpenBao token is passed to child processes in memory only;
it is never part of the container configuration.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import secrets
import shutil
import string
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

WORKSPACE = Path(os.environ.get("ASSETFLOW_ROOT", "/workspace"))
RUNTIME = Path(os.environ.get("AF_RUNTIME_DIR", "/run/af-runtime"))
KEYS = Path(os.environ.get("AF_KEYS_DIR", "/run/af-keys"))
ZITADEL_BOOTSTRAP = Path("/zitadel/bootstrap")
BACKEND_APP = Path(os.environ.get("AF_BACKEND_DIR", "/app"))

BAO_ADDR = os.environ.get("BAO_ADDR", "http://openbao:8200")
POSTGRES_HOST = "postgres"
POSTGRES_USER = "postgres"
APP_DATABASE = "assetflow"
TEST_DATABASE = "assetflow_test"

# uid:gid inside the images that read the files (postgres:16-alpine, zitadel, assetflow-backend).
POSTGRES_UID = 70
ZITADEL_UID = 1000
BACKEND_UID = 10001

ALNUM = string.ascii_letters + string.digits

# Database login roles: one LOGIN role per process kind, member of one NOLOGIN group role created by
# migration 0000 (assetflow_api, assetflow_worker, assetflow_migrator).
LOGIN_ROLES: dict[str, tuple[str, str, str]] = {
    # kind: (login role, group role, OpenBao KV path under secret/)
    "api": ("assetflow_api_login", "assetflow_api", "assetflow/database/api"),
    "worker": ("assetflow_worker_login", "assetflow_worker", "assetflow/database/worker"),
    "migrator": ("assetflow_migrator_login", "assetflow_migrator", "assetflow/migrator"),
}
# service directory in the runtime volume -> AppRole name written by openbao-apply.py
SERVICE_DIRS = {"api": "assetflow-api", "worker": "assetflow-worker"}
CONFIG_SUBDIRS = ("domains", "organizations", "templates")


def say(message: str) -> None:
    print(f"af-setup: {message}", flush=True)


def fail(message: str) -> int:
    print(f"af-setup: error: {message}", file=sys.stderr, flush=True)
    return 1


def random_value(length: int = 32) -> str:
    return "".join(secrets.choice(ALNUM) for _ in range(length))


def load_script(filename: str) -> Any:
    """Import a sibling script whose file name is not a valid module name."""
    path = WORKSPACE / "scripts" / filename
    spec = importlib.util.spec_from_file_location(filename.replace("-", "_").removesuffix(".py"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------- files in the runtime volume


def own(path: Path, uid: int, gid: int, mode: int) -> None:
    os.chown(path, uid, gid)
    os.chmod(path, mode)


def place(directory: Path, name: str, content: str, uid: int, gid: int, mode: int = 0o440) -> None:
    """Write one file atomically, owned by the user that reads it."""
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    temp = directory / f".{name}.tmp"
    # Runtime-secrets volume write, mode 0o440 owned by the reading user right below (plan R6).
    # CodeQL flags this as clear-text storage; dismissed by the owner as by-design (not suppressed
    # inline - this repo's Default Setup CodeQL does not honor inline suppression comments).
    temp.write_text(content, encoding="utf-8")
    own(temp, uid, gid, mode)
    temp.replace(target)


def own_dir(directory: Path, uid: int, gid: int) -> None:
    """Directory and the files in it belong to the reading user; nobody else can open them."""
    directory.mkdir(parents=True, exist_ok=True)
    own(directory, uid, gid, 0o750)
    for entry in directory.iterdir():
        if entry.is_file():
            own(entry, uid, gid, 0o440)


# ---------------------------------------------------------------- OpenBao


def bao_call(method: str, path: str, body: dict[str, Any] | None = None, token: str = "") -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f"{BAO_ADDR}/v1/{path}", data=data, method=method)
    if token:
        request.add_header("X-Vault-Token", token)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read()
            return response.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return exc.code, {}


def wait_until(what: str, probe: Callable[[], bool], seconds: float = 120.0) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if probe():
                return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(1.0)
    raise RuntimeError(f"{what} did not become ready in {seconds:.0f}s")


def initialize_and_unseal() -> str:
    """Init on the first start, unseal on every start; returns the root token (never printed)."""
    wait_until(
        "OpenBao",
        lambda: bao_call("GET", "sys/health?sealedcode=200&uninitcode=200&standbyok=true")[0] == 200,
    )
    KEYS.mkdir(parents=True, exist_ok=True)
    # 0700 (owner-only) is the stricter, correct permission for a secrets directory, not the loose
    # one the rule expects.
    os.chmod(KEYS, 0o700)  # nosemgrep
    key_file, token_file = KEYS / "unseal-key", KEYS / "root-token"
    _, health = bao_call("GET", "sys/health?sealedcode=200&uninitcode=200&standbyok=true")
    if not health.get("initialized"):
        status, payload = bao_call("PUT", "sys/init", {"secret_shares": 1, "secret_threshold": 1})
        if status != 200:
            raise RuntimeError(f"OpenBao init failed: HTTP {status}")
        key_file.write_text(payload["keys_base64"][0], encoding="utf-8")
        token_file.write_text(payload["root_token"], encoding="utf-8")
        os.chmod(key_file, 0o600)
        os.chmod(token_file, 0o600)
        say("OpenBao initialized (local dev unseal key stored in the assetflow_openbao_dev_keys volume)")
        _, health = bao_call("GET", "sys/health?sealedcode=200&uninitcode=200&standbyok=true")
    if not (key_file.exists() and token_file.exists()):
        raise RuntimeError(
            "OpenBao is initialized but the local dev key volume is empty. Its data cannot be unsealed: "
            "run `make dev-down RESET=1` to start from scratch."
        )
    if health.get("sealed"):
        status, _ = bao_call("PUT", "sys/unseal", {"key": key_file.read_text(encoding="utf-8").strip()})
        if status != 200:
            raise RuntimeError(f"OpenBao unseal failed: HTTP {status}")
        say("OpenBao unsealed")
    return token_file.read_text(encoding="utf-8").strip()


def ensure_kv(bao: Any, path: str, make: Callable[[], dict[str, str]]) -> None:
    """Create a KV v2 entry only when it does not exist (check-and-set 0); never overwrites."""
    if bao.get(f"secret/metadata/{path}") is not None:
        return
    status, payload = bao.call("POST", f"secret/data/{path}", {"options": {"cas": 0}, "data": make()})
    if status >= 400:
        raise RuntimeError(f"write secret/{path}: HTTP {status} {payload.get('errors', '')}")
    say(f"generated secret/{path} (value not shown)")


def kv_read(bao: Any, path: str) -> dict[str, str]:
    payload = bao.get(f"secret/data/{path}")
    if payload is None:
        raise RuntimeError(f"secret/{path} is missing in OpenBao")
    return {str(k): str(v) for k, v in payload["data"]["data"].items()}


def step_openbao() -> int:
    apply_script = load_script("openbao-apply.py")
    token = initialize_and_unseal()
    # The apply script keeps its login files in deploy/.secrets; here that is the runtime volume.
    apply_script.CREDENTIALS_DIR = RUNTIME
    os.environ["BAO_TOKEN"] = token
    try:
        rc = int(apply_script.main(["--generate-missing", "--issue-secret-ids"]))
        if rc != 0:
            return rc
        bao = apply_script.Bao(BAO_ADDR, token, None)
        for _login, _group, path in LOGIN_ROLES.values():
            ensure_kv(bao, path, lambda: {"password": random_value()})
        ensure_kv(bao, "assetflow/session", lambda: {"cookie_key": random_value(48)})
        postgres = kv_read(bao, "assetflow/postgres")
        zitadel_key = kv_read(bao, "assetflow/zitadel/masterkey")
        zitadel_db = kv_read(bao, "assetflow/zitadel/database")
        zitadel_admin = kv_read(bao, "assetflow/zitadel/admin")
    finally:
        os.environ.pop("BAO_TOKEN", None)

    RUNTIME.mkdir(parents=True, exist_ok=True)
    # A directory needs the execute bit to be traversable; 0644 (the rule's suggested default)
    # would break every read under it.
    os.chmod(RUNTIME, 0o755)  # nosemgrep
    # PostgreSQL: superuser password for POSTGRES_PASSWORD_FILE.
    place(
        RUNTIME / "postgres", "postgres-password", postgres["superuser_password"], POSTGRES_UID, POSTGRES_UID
    )
    own_dir(RUNTIME / "postgres", POSTGRES_UID, POSTGRES_UID)
    # Zitadel: masterkey (exactly 32 characters, no newline), database passwords, first-admin password.
    # Zitadel's database administrator is the PostgreSQL superuser of this one server.
    zdir = RUNTIME / "zitadel"
    place(zdir, "masterkey", zitadel_key["value"], ZITADEL_UID, ZITADEL_UID)
    secrets_yaml = (
        "Database:\n  Postgres:\n    User:\n"
        f"      Password: {json.dumps(zitadel_db['user_password'])}\n    Admin:\n"
        f"      Password: {json.dumps(postgres['superuser_password'])}\n"
    )
    place(zdir, "zitadel-secrets.yaml", secrets_yaml, ZITADEL_UID, ZITADEL_UID)
    steps_yaml = f"FirstInstance:\n  Org:\n    Human:\n      Password: {json.dumps(zitadel_admin['initial_password'])}\n"
    place(zdir, "zitadel-steps-secrets.yaml", steps_yaml, ZITADEL_UID, ZITADEL_UID)
    own_dir(zdir, ZITADEL_UID, ZITADEL_UID)
    # AppRole logins written by openbao-apply (role_id, secret_id): readable by the service user only.
    for directory in SERVICE_DIRS.values():
        own_dir(RUNTIME / directory, BACKEND_UID, BACKEND_UID)
    # Zitadel writes its first machine key here once; it runs as uid 1000.
    ZITADEL_BOOTSTRAP.mkdir(parents=True, exist_ok=True)
    own(ZITADEL_BOOTSTRAP, ZITADEL_UID, ZITADEL_UID, 0o700)
    say("openbao: done")
    return 0


# ---------------------------------------------------------------- Zitadel


def step_zitadel() -> int:
    apply_script = load_script("openbao-apply.py")
    token = (KEYS / "root-token").read_text(encoding="utf-8").strip()
    env = {
        **os.environ,
        "ASSETFLOW_ENV": "development",
        # Development environment, but results go to OpenBao (never to .env.local).
        "ASSETFLOW_SECRET_STORE": "openbao",
        "BAO_TOKEN": token,
        "HOME": "/tmp",
    }
    command = [
        "uv",
        "run",
        "--script",
        "--python",
        "3.12",
        str(WORKSPACE / "scripts" / "bootstrap_zitadel.py"),
    ]
    # `command` is a fixed argv built above, not user input; `env` is `{**os.environ, ...}`, not
    # attacker-controlled.
    result = subprocess.run([*command, "apply"], env=env, check=False)  # nosemgrep
    if result.returncode != 0:
        return fail("zitadel-apply failed (output above never contains secret values)")

    bao = apply_script.Bao(BAO_ADDR, token, None)
    idp = kv_read(bao, "assetflow/idp")
    for kind, directory in SERVICE_DIRS.items():
        render_service_config(kind, RUNTIME / directory, idp)
        own_dir(RUNTIME / directory, BACKEND_UID, BACKEND_UID)
    say("zitadel: done")
    return 0


def render_service_config(kind: str, directory: Path, idp: dict[str, str]) -> None:
    """The service's config file: the repository config with OpenBao, OIDC and the dev login roles."""
    import yaml

    config = yaml.safe_load((WORKSPACE / "config" / "assetflow.yaml").read_text(encoding="utf-8"))
    role_id = (directory / "role_id").read_text(encoding="utf-8").strip()
    providers = config["providers"]
    providers["secrets"] = {
        "type": "openbao",
        # secret_id_file is relative to this file's folder.
        "settings": {"address": BAO_ADDR, "role_id": role_id, "secret_id_file": "secret_id"},
    }
    providers["auth"] = {
        "type": "oidc",
        "settings": {
            "issuer": idp["issuer"],
            "client_id": idp["client_id"],
            "client_secret": "secret://assetflow/idp#client_secret",
            "audience": idp["project_id"],
        },
    }
    providers["events"] = {"type": "postgres", "settings": {}}
    providers["telemetry"] = {"type": "noop", "settings": {}}
    config["env"] = "${ASSETFLOW_ENV}"
    config["session_cookie_key"] = "secret://assetflow/session#cookie_key"
    app_url = os.environ.get("APP_URL", "http://localhost:18080").rstrip("/")
    origins = config.setdefault("platform", {}).setdefault("allowed_origins", [])
    if app_url not in origins:
        origins.append(app_url)
    for role, (login, _group, path) in LOGIN_ROLES.items():
        config["database"][role] = {"user": login, "password": f"secret://{path}#password"}
    (directory / "assetflow.yaml").write_text(
        "# Generated by scripts/dev_setup.py (af-setup). References only, no credential values.\n"
        + yaml.safe_dump(config, sort_keys=False),
        encoding="utf-8",
    )
    for sub in CONFIG_SUBDIRS:
        source = WORKSPACE / "config" / sub
        if source.is_dir():
            shutil.rmtree(directory / sub, ignore_errors=True)
            shutil.copytree(source, directory / sub)
    for path in directory.rglob("*"):
        os.chown(path, BACKEND_UID, BACKEND_UID)
        os.chmod(path, 0o750 if path.is_dir() else 0o440)


# ---------------------------------------------------------------- migrate


def _ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


async def provision_database(password: str, role_passwords: dict[str, str]) -> None:
    import asyncpg

    conn = await asyncpg.connect(
        host=POSTGRES_HOST, user=POSTGRES_USER, password=password, database=APP_DATABASE, timeout=30
    )
    try:
        for kind, (login, group, _path) in LOGIN_ROLES.items():
            exists = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", login)
            verb = "ALTER" if exists else "CREATE"
            await conn.execute(f"{verb} ROLE {_ident(login)} LOGIN PASSWORD {_literal(role_passwords[kind])}")
            await conn.execute(f"GRANT {_ident(group)} TO {_ident(login)}")
        if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", TEST_DATABASE):
            await conn.execute(f"CREATE DATABASE {_ident(TEST_DATABASE)}")
    finally:
        await conn.close()


def step_migrate() -> int:
    apply_script = load_script("openbao-apply.py")
    token = (KEYS / "root-token").read_text(encoding="utf-8").strip()
    bao = apply_script.Bao(BAO_ADDR, token, None)
    role_passwords = {kind: kv_read(bao, path)["password"] for kind, (_l, _g, path) in LOGIN_ROLES.items()}

    # Migration 0000 creates the group roles, which needs CREATEROLE: the PostgreSQL superuser of this
    # local server runs the migrations; the login roles are created right after. The DSN's password is
    # a secret:// reference (AF-047): backend/migrations/env.py resolves it through OpenBao just before
    # connecting, using BAO_ADDR/BAO_TOKEN below, so the real password is never written to a file here,
    # only the reference is.
    dsn = (
        f"postgresql://{POSTGRES_USER}:secret://assetflow/postgres#superuser_password"
        f"@{POSTGRES_HOST}:5432/{APP_DATABASE}"
    )
    # Fixed argv; `env` is `{**os.environ, ...}` plus a DSN reference and OpenBao address/token, none
    # of it attacker-controlled.
    env = {**os.environ, "ASSETFLOW_MIGRATION_DATABASE_URL": dsn, "BAO_ADDR": BAO_ADDR, "BAO_TOKEN": token}
    result = subprocess.run(
        [  # nosemgrep
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(BACKEND_APP / "alembic.ini"),
            "upgrade",
            "head",
        ],
        cwd=BACKEND_APP,
        env=env,
        check=False,
    )
    if result.returncode != 0:
        return fail("alembic upgrade head failed")
    password = kv_read(bao, "assetflow/postgres")["superuser_password"]
    asyncio.run(provision_database(password, role_passwords))
    say("migrate: done (migrations applied, database login roles in place)")
    return 0


# ---------------------------------------------------------------- sign-in check


def step_signin() -> int:
    token = (KEYS / "root-token").read_text(encoding="utf-8").strip()
    env = {**os.environ, "BAO_TOKEN": token, "HOME": "/tmp"}
    command = [
        "uv",
        "run",
        "--script",
        "--python",
        "3.12",
        str(WORKSPACE / "scripts" / "dev_signin_check.py"),
    ]
    # `command` is a fixed argv built above, not user input; `env` is `{**os.environ, ...}`, not
    # attacker-controlled.
    return subprocess.run(command, env=env, check=False).returncode  # nosemgrep


def step_admin_password() -> int:
    """Point whoever calls this step at the real one; never print the password here.

    `scripts/dev.sh admin-password` (hence `make dev-admin-password`) no longer routes through this
    step or this file: it reads OpenBao directly in an inline interpreter, so the value never passes
    through a committed Python source file.
    """
    say("run: make dev-admin-password")
    return 0


STEPS: dict[str, Callable[[], int]] = {
    "admin-password": step_admin_password,
    "openbao": step_openbao,
    "zitadel": step_zitadel,
    "migrate": step_migrate,
    "signin": step_signin,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("step", choices=sorted(STEPS))
    args = parser.parse_args(argv)
    try:
        return STEPS[args.step]()
    except (RuntimeError, OSError, KeyError) as exc:
        return fail(f"{args.step}: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    sys.exit(main())
