# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""scripts/check-ports.py: the port preflight of `make up-full` and `make up-identity` (P2-13).

Run: make test-scripts
"""

from __future__ import annotations

import importlib.util
import socket
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "check-ports.py"
_spec = importlib.util.spec_from_file_location("check_ports", SCRIPT)
assert _spec is not None and _spec.loader is not None
check_ports: Any = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_ports)


@pytest.fixture(autouse=True)
def _no_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check_ports, "assetflow_ports", lambda: set())
    monkeypatch.setattr(check_ports, "is_free", lambda port: True)
    monkeypatch.setattr(check_ports, "existing_containers", dict)


def test_every_default_host_port_is_above_9000() -> None:
    for profile, variables in check_ports.PROFILES.items():
        assert all(port > 9000 for port in variables.values()), profile


def test_the_defaults_pass_when_everything_is_free() -> None:
    assert check_ports.problems("full", {}) == []
    assert check_ports.problems("identity", {}) == []


def test_a_port_at_or_below_9000_is_refused() -> None:
    found = check_ports.problems("full", {"API_HOST_PORT": "8080"})
    assert len(found) == 1
    assert "API_HOST_PORT=8080" in found[0] and "above 9000" in found[0]
    assert check_ports.problems("full", {"POSTGRES_HOST_PORT": "9000"})
    assert check_ports.problems("full", {"POSTGRES_HOST_PORT": "70000"})


def test_a_port_in_use_is_named_with_the_variable_that_moves_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check_ports, "is_free", lambda port: port != 19200)
    found = check_ports.problems("full", {})
    assert found == [
        "OPENBAO_HOST_PORT=19200: port 19200 is already in use. Set OPENBAO_HOST_PORT to a free port above 9000."
    ]


def test_a_port_held_by_our_own_stack_is_fine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check_ports, "is_free", lambda port: False)
    monkeypatch.setattr(check_ports, "assetflow_ports", lambda: {19200, 15432, 19081, 18080})
    assert check_ports.problems("full", {}) == []


def test_two_services_may_not_share_a_port() -> None:
    found = check_ports.problems("full", {"API_HOST_PORT": "19200"})
    assert any("chosen twice" in m for m in found)


def test_a_value_that_is_not_a_number_is_reported() -> None:
    assert check_ports.problems("full", {"API_HOST_PORT": "http"}) == [
        "API_HOST_PORT='http' is not a port number"
    ]


def test_an_override_is_used_and_an_empty_value_means_the_default() -> None:
    assert check_ports.chosen_ports("full", {"API_HOST_PORT": "20000", "POSTGRES_HOST_PORT": ""}) == {
        "OPENBAO_HOST_PORT": 19200,
        "POSTGRES_HOST_PORT": 15432,
        "ZITADEL_EXTERNALPORT": 19081,
        "API_HOST_PORT": 20000,
    }


def test_the_env_file_is_read(tmp_path: Path) -> None:
    env = tmp_path / ".env.local"
    env.write_text(
        '# a comment\nAPI_HOST_PORT=21000\nZITADEL_MASTERKEY="x y"\n\nBAD LINE\n', encoding="utf-8"
    )
    assert check_ports.read_env_file(env) == {"API_HOST_PORT": "21000", "ZITADEL_MASTERKEY": "x y"}
    assert check_ports.read_env_file(tmp_path / "absent") == {}


def test_a_real_listener_is_seen_as_in_use(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.undo()  # use the real is_free for this one
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        busy = sock.getsockname()[1]
        assert check_ports.is_free(busy) is False
    assert check_ports.is_free(busy) is True


def test_dev_profile_ports_are_also_above_9000() -> None:
    assert check_ports.problems("dev", {}) == []
    assert all(port > 9000 for port in check_ports.PROFILES["dev"].values())


def test_dev_optional_ports_are_only_checked_when_the_profile_is_on() -> None:
    assert check_ports.chosen_ports("dev", {}) == check_ports.PROFILES["dev"]
    with_mail = check_ports.chosen_ports("dev", {"MAIL": "1"})
    assert "MAILPIT_WEB_PORT" in with_mail
    assert "MAILPIT_WEB_PORT" not in check_ports.chosen_ports("dev", {})


def test_a_foreign_container_owning_an_af_name_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        check_ports, "existing_containers", lambda: {"af-postgres": ("", "some-other-project", "")}
    )
    found = check_ports.problems("dev", {})
    assert any("af-postgres" in m and "does not belong to AssetFlow" in m for m in found)


def test_a_container_of_this_project_but_another_stack_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        check_ports,
        "existing_containers",
        lambda: {"af-postgres": ("assetflow", "assetflow-minimal", "deploy/compose.minimal.yml")},
    )
    found = check_ports.problems("dev", {})
    assert any("af-postgres" in m and "another AssetFlow stack" in m for m in found)


def test_a_container_of_this_stack_is_fine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        check_ports,
        "existing_containers",
        lambda: {"af-postgres": ("assetflow", "assetflow", "deploy/compose.dev.yml")},
    )
    assert check_ports.problems("dev", {}) == []


def test_the_command_line_exits_non_zero_and_says_nothing_was_touched(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("API_HOST_PORT", "8080")
    assert check_ports.main(["full", "--env-file", str(tmp_path / "none")]) == 1
    err = capsys.readouterr().err
    assert "API_HOST_PORT=8080" in err and "no container was touched" in err
    monkeypatch.delenv("API_HOST_PORT")
    assert check_ports.main(["identity", "--env-file", str(tmp_path / "none")]) == 0
