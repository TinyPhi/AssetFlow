# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Config loader: schema, exact error paths, env interpolation, production guards, CLI (§B7, §B6.1)."""

from __future__ import annotations

import logging
import secrets as pysecrets
import textwrap
from pathlib import Path

import pytest

from app.core.config import (
    DEFAULT_CONFIG_PATH,
    AppConfig,
    ConfigError,
    format_path,
    is_secret_ref,
    load_config,
    main,
    refuse_development_password,
)

BASE = """
env: {env}
session_cookie_key: "secret://session/cookie#key"
platform:
  admins: ["admin-subject"]
providers:
  auth: {{type: {auth}}}
  secrets: {{type: {secrets}}}
  telemetry: {{type: noop}}
  events: {{type: inmemory}}
database:
  host: localhost
  name: assetflow
  sslmode: verify-full
  api: {{user: assetflow_api, password: "{password}"}}
  worker: {{user: assetflow_worker, password: "secret://database/worker#password"}}
  migrator: {{user: assetflow_migrator, password: "secret://database/migrator#password"}}
"""

COOKIE_LINE = 'session_cookie_key: "secret://session/cookie#key"\n'


def write(tmp_path: Path, text: str, name: str = "assetflow.yaml") -> Path:
    path = tmp_path / name
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def base(
    env: str = "development",
    auth: str = "mock",
    secrets: str = "file",
    api_ref: str = "secret://database/api#password",
) -> str:
    return BASE.format(env=env, auth=auth, secrets=secrets, password=api_ref)


def paths(exc: pytest.ExceptionInfo[ConfigError]) -> list[str]:
    return [path for path, _ in exc.value.errors]


# ------------------------------------------------------------------------------------ loading


def test_repo_config_is_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASSETFLOW_ENV", "test")
    monkeypatch.setenv("ASSETFLOW_AUTH_PROVIDER", "mock")
    cfg = load_config(DEFAULT_CONFIG_PATH)
    assert cfg.env in {"development", "test"}
    for role in ("api", "worker", "migrator"):
        assert is_secret_ref(getattr(cfg.database, role).password)


def test_load_valid_file(tmp_path: Path) -> None:
    cfg = load_config(write(tmp_path, base()))
    assert cfg.env == "development"
    assert cfg.providers.auth.type == "mock"
    assert cfg.database.port == 5432
    assert cfg.database.statement_timeout_ms == 15000
    assert cfg.database.api.password == "secret://database/api#password"
    assert cfg.source == (tmp_path / "assetflow.yaml").resolve()


def test_explicit_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="config file not found"):
        load_config(tmp_path / "absent.yaml")


def test_env_var_selects_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASSETFLOW_CONFIG", str(write(tmp_path, base(env="test"))))
    assert load_config().env == "test"


def test_missing_file_named_by_env_var_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASSETFLOW_CONFIG", str(tmp_path / "absent.yaml"))
    with pytest.raises(ConfigError, match="config file not found"):
        load_config()


def test_yaml_syntax_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="YAML syntax error"):
        load_config(write(tmp_path, "env: [unclosed\n"))


def test_top_level_must_be_mapping(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="top level must be a mapping"):
        load_config(write(tmp_path, "- a\n- b\n"))


# ------------------------------------------------------------------------------- exact paths


def test_format_path() -> None:
    assert (
        format_path(["maintenance", "priority_matrix", "map", 1, 2])
        == "maintenance.priority_matrix.map[1][2]"
    )
    assert format_path([]) == ""


def test_invalid_type_reports_exact_path(tmp_path: Path) -> None:
    text = base().replace("  host: localhost", "  host: localhost\n  port: not-a-port")
    with pytest.raises(ConfigError) as exc:
        load_config(write(tmp_path, text))
    assert paths(exc) == ["database.port"]


def test_list_index_path(tmp_path: Path) -> None:
    text = base().replace('admins: ["admin-subject"]', 'admins: ["ok", {bad: 1}]')
    with pytest.raises(ConfigError) as exc:
        load_config(write(tmp_path, text))
    assert paths(exc) == ["platform.admins[1]"]


def test_unknown_keys_are_forbidden(tmp_path: Path) -> None:
    text = base().replace("  host: localhost", "  host: localhost\n  hots: typo") + "server: {port: 1}\n"
    with pytest.raises(ConfigError) as exc:
        load_config(write(tmp_path, text))
    assert sorted(paths(exc)) == ["database.hots", "server"]


def test_old_schema_is_rejected(tmp_path: Path) -> None:
    text = base() + "auth:\n  provider: mock\n"
    with pytest.raises(ConfigError) as exc:
        load_config(write(tmp_path, text))
    assert paths(exc) == ["auth"]


def test_database_section_is_required(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as exc:
        load_config(write(tmp_path, "env: development\n"))
    assert paths(exc) == ["database"]


def test_pool_bounds(tmp_path: Path) -> None:
    text = base().replace("  host: localhost", "  host: localhost\n  pool_min: 5\n  pool_max: 2")
    with pytest.raises(ConfigError) as exc:
        load_config(write(tmp_path, text))
    assert paths(exc) == ["database"]


# ----------------------------------------------------------------------- env interpolation


def test_env_interpolation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AF_TEST_DB_HOST", "db.internal")
    text = (
        base()
        .replace("host: localhost", 'host: "${AF_TEST_DB_HOST}"')
        .replace("name: assetflow", 'name: "${AF_TEST_UNSET_NAME:-fallback_db}"')
    )
    monkeypatch.delenv("AF_TEST_UNSET_NAME", raising=False)
    cfg = load_config(write(tmp_path, text))
    assert cfg.database.host == "db.internal"
    assert cfg.database.name == "fallback_db"


def test_unset_env_without_default_is_an_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AF_TEST_MISSING", raising=False)
    text = base().replace("host: localhost", 'host: "${AF_TEST_MISSING}"')
    with pytest.raises(ConfigError) as exc:
        load_config(write(tmp_path, text))
    assert exc.value.errors == [("database.host", "environment variable AF_TEST_MISSING is not set")]


# ------------------------------------------------------------------------- secret references


@pytest.mark.parametrize(
    ("ref", "ok"),
    [
        ("secret://database/api#password", True),
        ("secret://orgs/0192/channels/email#token", True),
        ("secret://database#password", False),
        ("secret://database/api", False),
        ("secret://../etc#passwd", False),
        ("secret://database/../x#k", False),
        ("secret://database/api#..", False),
        ("plain-value", False),
    ],
)
def test_is_secret_ref(ref: str, ok: bool) -> None:
    assert is_secret_ref(ref) is ok


def test_literal_password_is_rejected_in_development(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as exc:
        load_config(write(tmp_path, base(api_ref="literal-value")))
    assert paths(exc) == ["database.api.password"]


def test_env_interpolated_password_allowed_in_development(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = pysecrets.token_hex(16)
    monkeypatch.setenv("AF_TEST_DB_PASSWORD", value)
    cfg = load_config(write(tmp_path, base(api_ref="${AF_TEST_DB_PASSWORD}")))
    assert cfg.database.api.password == value


def test_password_with_env_default_is_not_an_interpolation(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as exc:
        load_config(write(tmp_path, base(api_ref="${AF_TEST_NOPE:-literal}")))
    assert paths(exc) == ["database.api.password"]


# ------------------------------------------------------------------------ production guards


def test_production_refuses_mock_auth_and_file_secrets(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as exc:
        load_config(write(tmp_path, base(env="production")))
    assert paths(exc) == ["providers.auth.type", "providers.secrets.type"]


def test_production_refuses_non_secret_password(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AF_TEST_DB_PASSWORD", "from-env")
    text = base(env="production", auth="oidc", secrets="openbao", api_ref="${AF_TEST_DB_PASSWORD}")
    with pytest.raises(ConfigError) as exc:
        load_config(write(tmp_path, text))
    assert paths(exc) == ["database.api.password"]


def test_production_fallbacks_are_refused(tmp_path: Path) -> None:
    text = base(env="production", auth="oidc", secrets="openbao").replace(
        "  auth: {type: oidc}\n  secrets: {type: openbao}\n", ""
    )
    with pytest.raises(ConfigError) as exc:
        load_config(write(tmp_path, text))
    assert paths(exc) == ["providers.auth.type", "providers.secrets.type"]


def test_production_refuses_disabled_scrubbing(tmp_path: Path) -> None:
    text = base(env="production", auth="oidc", secrets="openbao").replace(
        "telemetry: {type: noop}", "telemetry: {type: otel, settings: {scrub: false}}"
    )
    with pytest.raises(ConfigError) as exc:
        load_config(write(tmp_path, text))
    assert paths(exc) == ["providers.telemetry.settings.scrub"]


def test_production_valid(tmp_path: Path) -> None:
    cfg = load_config(write(tmp_path, base(env="production", auth="oidc", secrets="openbao")))
    assert cfg.env == "production"


def test_production_refuses_open_provisioning(tmp_path: Path) -> None:
    (tmp_path / "organizations").mkdir()
    write(tmp_path / "organizations", "slug: acme\nprovisioning: open\n", "acme.yaml")
    cfg_file = write(tmp_path, base(env="production", auth="oidc", secrets="openbao"))
    with pytest.raises(ConfigError) as exc:
        load_config(cfg_file)
    assert paths(exc) == ["organizations/acme.yaml.provisioning"]

    allowed = base(env="production", auth="oidc", secrets="openbao").replace(
        "platform:\n", "platform:\n  allow_open_provisioning: true\n"
    )
    assert load_config(write(tmp_path, allowed)).platform.allow_open_provisioning is True


def test_open_provisioning_allowed_outside_production(tmp_path: Path) -> None:
    (tmp_path / "organizations").mkdir()
    write(tmp_path / "organizations", "slug: acme\nprovisioning: open\n", "acme.yaml")
    assert load_config(write(tmp_path, base())).env == "development"


def test_guards_apply_to_model_validate_directly() -> None:
    data = {
        "env": "production",
        "session_cookie_key": "secret://session/cookie#key",
        "database": {
            "sslmode": "verify-full",
            "host": "h",
            "name": "n",
            "api": {"user": "u", "password": "secret://database/api#password"},
            "worker": {"user": "u", "password": "secret://database/worker#password"},
            "migrator": {"user": "u", "password": "secret://database/migrator#password"},
        },
    }
    with pytest.raises(ConfigError) as exc:
        AppConfig.model_validate(data)
    assert paths(exc) == ["providers.auth.type", "providers.secrets.type"]


# ------------------------------------------------------------------------------- fallbacks


def test_missing_pillars_fall_back_with_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    text = base().replace("  telemetry: {type: noop}\n  events: {type: inmemory}\n", "")
    with caplog.at_level(logging.WARNING, logger="app.core.config"):
        cfg = load_config(write(tmp_path, text))
    assert cfg.providers.telemetry.type == "noop"
    assert cfg.providers.telemetry.is_fallback
    assert cfg.providers.events.type == "inmemory"
    assert not cfg.providers.auth.is_fallback
    assert "providers.telemetry is not configured" in caplog.text
    assert "providers.events is not configured" in caplog.text
    assert "providers.auth is not configured" not in caplog.text


# -------------------------------------------------------------------------------------- CLI


def test_cli_invalid(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", str(write(tmp_path, base(env="production")))]) == 1
    assert "providers.auth.type" in capsys.readouterr().err


def test_cli_missing_file_and_usage(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", str(tmp_path / "absent.yaml")]) == 1
    assert main([]) == 1
    assert "usage" in capsys.readouterr().err


# --------------------------------------------------------------------------- email channel (P6-04)


def _with_email(text: str, block: str) -> str:
    return text.rstrip() + "\n" + textwrap.dedent(block)


def test_email_defaults_are_safe_and_off() -> None:
    from app.core.config import EmailChannelConfig  # noqa: PLC0415 - only this test needs it

    cfg = EmailChannelConfig()
    assert (cfg.enabled, cfg.port, cfg.security, cfg.allow_private_addresses) == (
        False,
        587,
        "starttls",
        False,
    )
    assert cfg.password is None


def test_email_password_must_be_a_secret_reference(tmp_path: Path) -> None:
    block = """
    notifications:
      channels:
        email:
          enabled: true
          password: "a-literal-password"
    """
    with pytest.raises(ConfigError) as exc:
        load_config(write(tmp_path, _with_email(base(), block)))
    assert paths(exc) == ["notifications.channels.email.password"]


def test_email_password_as_a_secret_reference_is_accepted(tmp_path: Path) -> None:
    block = """
    notifications:
      channels:
        email:
          enabled: true
          host: smtp.example.test
          username: relay-user
          password: secret://smtp/relay#password
    """
    cfg = load_config(write(tmp_path, _with_email(base(), block)))
    assert cfg.notifications.channels.email.password == "secret://smtp/relay#password"


@pytest.mark.parametrize(
    ("setting", "path"),
    [
        ("security: none", "notifications.channels.email.security"),
        ("allow_private_addresses: true", "notifications.channels.email.allow_private_addresses"),
    ],
)
def test_production_refuses_unsafe_email_settings(tmp_path: Path, setting: str, path: str) -> None:
    block = f"""
    notifications:
      channels:
        email:
          enabled: true
          {setting}
    """
    text = _with_email(base(env="production", auth="oidc", secrets="openbao"), block)
    with pytest.raises(ConfigError) as exc:
        load_config(write(tmp_path, text))
    assert paths(exc) == [path]


def test_unsafe_email_settings_are_allowed_when_email_is_off_or_outside_production(tmp_path: Path) -> None:
    block = """
    notifications:
      channels:
        email:
          enabled: true
          security: none
          allow_private_addresses: true
    """
    assert (
        load_config(write(tmp_path, _with_email(base(), block))).notifications.channels.email.security
        == "none"
    )
    off = block.replace("enabled: true", "enabled: false")
    assert load_config(
        write(tmp_path, _with_email(base(env="production", auth="oidc", secrets="openbao"), off))
    )


def test_email_port_and_security_are_validated(tmp_path: Path) -> None:
    block = """
    notifications:
      channels:
        email:
          port: 70000
          security: plaintext
    """
    with pytest.raises(ConfigError) as exc:
        load_config(write(tmp_path, _with_email(base(), block)))
    assert paths(exc) == ["notifications.channels.email.port", "notifications.channels.email.security"]


# ------------------------------------------------------------------------- session cookie key


@pytest.mark.parametrize("env", ["staging", "production"])
def test_session_cookie_key_is_required_outside_development_and_test(tmp_path: Path, env: str) -> None:
    text = base(env=env, auth="oidc", secrets="openbao").replace(COOKIE_LINE, "")
    with pytest.raises(ConfigError) as exc:
        load_config(write(tmp_path, text))
    assert paths(exc) == ["session_cookie_key"]


@pytest.mark.parametrize("env", ["development", "test"])
def test_session_cookie_key_is_optional_in_development_and_test(tmp_path: Path, env: str) -> None:
    text = base(env=env).replace(COOKIE_LINE, "")
    assert load_config(write(tmp_path, text)).session_cookie_key is None


def test_session_cookie_key_must_be_a_secret_reference(tmp_path: Path) -> None:
    text = base().replace("secret://session/cookie#key", "a-literal-key")
    with pytest.raises(ConfigError) as exc:
        load_config(write(tmp_path, text))
    assert paths(exc) == ["session_cookie_key"]


# ------------------------------------------------------------------- env, guards and secrets


def test_env_has_no_default(tmp_path: Path) -> None:
    text = base().replace("env: development\n", "")
    with pytest.raises(ConfigError) as exc:
        load_config(write(tmp_path, text))
    assert paths(exc) == ["env"]


def test_unset_env_variable_in_the_repo_config_refuses_boot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ASSETFLOW_ENV", raising=False)
    with pytest.raises(ConfigError) as exc:
        load_config(DEFAULT_CONFIG_PATH)
    assert ("env", "environment variable ASSETFLOW_ENV is not set") in exc.value.errors


def test_repo_config_does_not_default_to_mock_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASSETFLOW_ENV", "test")
    monkeypatch.delenv("ASSETFLOW_AUTH_PROVIDER", raising=False)
    with pytest.raises(ConfigError) as exc:
        load_config(DEFAULT_CONFIG_PATH)
    assert paths(exc) == ["providers.auth.type"]


def test_staging_refuses_mock_auth_and_file_secrets(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as exc:
        load_config(write(tmp_path, base(env="staging")))
    assert paths(exc) == ["providers.auth.type", "providers.secrets.type"]


def test_staging_refuses_non_secret_password(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AF_TEST_DB_PASSWORD", "from-env")
    text = base(env="staging", auth="oidc", secrets="openbao", api_ref="${AF_TEST_DB_PASSWORD}")
    with pytest.raises(ConfigError) as exc:
        load_config(write(tmp_path, text))
    assert paths(exc) == ["database.api.password"]


def test_oidc_client_secret_must_be_a_reference_outside_development(tmp_path: Path) -> None:
    text = base(env="staging", auth="oidc", secrets="openbao").replace(
        "auth: {type: oidc}", "auth: {type: oidc, settings: {client_secret: plain-secret}}"
    )
    with pytest.raises(ConfigError) as exc:
        load_config(write(tmp_path, text))
    assert paths(exc) == ["providers.auth.settings.client_secret"]
    ok = text.replace("plain-secret", '"secret://oidc/client#secret"')
    assert load_config(write(tmp_path, ok, "ok.yaml")).env == "staging"


def test_openbao_static_token_is_refused_outside_development(tmp_path: Path) -> None:
    text = base(env="staging", auth="oidc", secrets="openbao").replace(
        "secrets: {type: openbao}", "secrets: {type: openbao, settings: {token: s.static}}"
    )
    with pytest.raises(ConfigError) as exc:
        load_config(write(tmp_path, text))
    assert paths(exc) == ["providers.secrets.settings.token"]
    assert (
        load_config(write(tmp_path, text.replace("staging", "development"), "dev.yaml")).env == "development"
    )


def test_database_sslmode_defaults_to_prefer_and_is_validated(tmp_path: Path) -> None:
    text = base().replace("  sslmode: verify-full\n", "")
    assert load_config(write(tmp_path, text)).database.sslmode == "prefer"
    with pytest.raises(ConfigError) as exc:
        load_config(write(tmp_path, base().replace("verify-full", "sometimes"), "bad.yaml"))
    assert paths(exc) == ["database.sslmode"]


@pytest.mark.parametrize("env", ["staging", "production"])
@pytest.mark.parametrize("mode", ["disable", "prefer", "require", "verify-ca"])
def test_guarded_envs_require_verify_full(tmp_path: Path, env: str, mode: str) -> None:
    text = base(env=env, auth="oidc", secrets="openbao").replace("verify-full", mode)
    with pytest.raises(ConfigError) as exc:
        load_config(write(tmp_path, text))
    assert paths(exc) == ["database.sslmode"]


def test_development_password_is_refused_outside_development() -> None:
    with pytest.raises(ConfigError) as exc:
        refuse_development_password("production", "assetflow_dev_password", "database.api.password")
    assert [p for p, _ in exc.value.errors] == ["database.api.password"]
    refuse_development_password("development", "assetflow_dev_password", "database.api.password")
    refuse_development_password("production", "x9!rQ-long-random", "database.api.password")


def test_guarded_config_flags_database_for_password_checks(tmp_path: Path) -> None:
    prod = load_config(write(tmp_path, base(env="production", auth="oidc", secrets="openbao")))
    dev = load_config(write(tmp_path, base(), "dev.yaml"))
    assert prod.database.refuse_development_passwords is True
    assert dev.database.refuse_development_passwords is False


def test_unknown_role_keys_in_org_files_warn(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    (tmp_path / "organizations").mkdir()
    write(
        tmp_path / "organizations",
        "slug: acme\nidp:\n  granted_roles: [admin, not_a_role]\n",
        "acme.yaml",
    )
    with caplog.at_level(logging.WARNING, logger="app.core.config"):
        load_config(write(tmp_path, base()))
    assert "'not_a_role'" in caplog.text
    assert "'admin'" not in caplog.text
