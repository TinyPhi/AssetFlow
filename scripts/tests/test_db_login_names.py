# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for database login names consistency across config and init scripts (P5-00, ADR-0019).

Verifies that config/assetflow.yaml defaults and deploy/postgres/init-minimal.sh
use matching assetflow_<kind>_login names.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_FILE = REPO_ROOT / "config" / "assetflow.yaml"
INIT_SCRIPT = REPO_ROOT / "deploy" / "postgres" / "init-minimal.sh"

ROLES = ("api", "worker", "migrator")
EXPECTED_LOGINS = {
    "api": "assetflow_api_login",
    "worker": "assetflow_worker_login",
    "migrator": "assetflow_migrator_login",
}


def _extract_default(raw: str) -> str:
    match = re.match(r"^\$\{[A-Za-z0-9_]+:-([A-Za-z0-9_]+)\}$", raw.strip())
    if match:
        return match.group(1)
    return raw.strip()


def test_config_login_names_match_standard() -> None:
    data = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))
    db = data.get("database", {})

    for role, expected_name in EXPECTED_LOGINS.items():
        role_cfg = db.get(role, {})
        user_val = role_cfg.get("user", "")
        default_name = _extract_default(user_val)
        assert default_name == expected_name, (
            f"config database.{role}.user default {default_name!r} does not match {expected_name!r}"
        )
        assert not default_name.endswith("_user"), (
            f"config database.{role}.user default {default_name!r} must not use legacy '_user' suffix"
        )


def test_init_script_creates_matching_login_users() -> None:
    content = INIT_SCRIPT.read_text(encoding="utf-8")

    # Match roles created with LOGIN
    created_roles = set(re.findall(r"CREATE\s+ROLE\s+([A-Za-z0-9_]+)\s+WITH\s+LOGIN", content))

    for role, expected_name in EXPECTED_LOGINS.items():
        assert expected_name in created_roles, (
            f"deploy/postgres/init-minimal.sh is missing CREATE ROLE for login user {expected_name!r} ({role})"
        )

    # Ensure no legacy _user role names exist in the init script
    legacy_users = re.findall(r"assetflow_[A-Za-z0-9_]+_user", content)
    assert not legacy_users, f"Found legacy '_user' role names in init script: {legacy_users}"


def test_config_and_init_script_login_names_are_synchronized() -> None:
    data = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))
    db = data.get("database", {})
    init_content = INIT_SCRIPT.read_text(encoding="utf-8")

    config_logins = set()
    for role in ROLES:
        val = db.get(role, {}).get("user", "")
        config_logins.add(_extract_default(val))

    init_logins = set(re.findall(r"CREATE\s+ROLE\s+([A-Za-z0-9_]+)\s+WITH\s+LOGIN", init_content))

    missing_in_init = config_logins - init_logins
    assert not missing_in_init, f"Login names in config missing from init script: {missing_in_init}"

    expected_all = set(EXPECTED_LOGINS.values())
    assert config_logins == expected_all
    assert expected_all.issubset(init_logins)


COMPOSE_FILE = REPO_ROOT / "deploy" / "compose.minimal.yml"


def test_roles_are_applied_on_every_start_before_migrations() -> None:
    # An init-only script would leave existing databases on old login names (P5-00 review).
    services = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))["services"]
    db_roles = services["db-roles"]
    assert any("init-minimal.sh" in str(v) for v in db_roles["volumes"])
    assert services["migrate"]["depends_on"]["db-roles"]["condition"] == "service_completed_successfully"
    postgres_mounts = " ".join(str(v) for v in services["postgres"]["volumes"])
    assert "docker-entrypoint-initdb.d" not in postgres_mounts


def test_init_script_renames_legacy_logins() -> None:
    content = INIT_SCRIPT.read_text(encoding="utf-8")
    assert "RENAME TO" in content
    for role in ROLES:
        assert f"'{role}'" in content, f"legacy rename does not cover {role!r}"
