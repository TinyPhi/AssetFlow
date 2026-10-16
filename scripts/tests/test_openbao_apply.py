# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for scripts/openbao-apply.py against a fake OpenBao client.

Run: make test-scripts
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "openbao-apply.py"
_spec = importlib.util.spec_from_file_location("openbao_apply", SCRIPT)
assert _spec is not None and _spec.loader is not None
apply = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(apply)

ROLE_ID_VALUE = "role-id-value"
ISSUED_VALUE = "issued-value-1"


class FakeBao:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.kv_written: dict[str, dict[str, Any]] = {}
        self.lookup_valid = False
        self.existing: dict[str, dict[str, Any]] = {}
        self.bodies: dict[str, dict[str, Any] | None] = {}
        self.audit_devices: dict[str, Any] = {}

    def ok(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((method, path))
        self.bodies[path] = body
        if method == "GET" and path == "sys/audit":
            return {"data": self.audit_devices}
        if path.endswith("/role-id"):
            return {"data": {"role_id": ROLE_ID_VALUE}}
        if path.endswith("/secret-id"):
            return {"data": {"secret_id": ISSUED_VALUE}}
        return {}

    def get(self, path: str) -> dict[str, Any] | None:
        return self.existing.get(path)

    def call(self, method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        self.calls.append((method, path))
        if path.endswith("/secret-id/lookup"):
            return (200, {"data": {"x": 1}}) if self.lookup_valid else (400, {})
        self.kv_written[path] = (body or {}).get("data", {})
        return 200, {}


@pytest.fixture
def applier(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(apply, "CREDENTIALS_DIR", tmp_path)
    return apply.Applier(FakeBao(), ["172.28.0.0/24"])  # type: ignore[arg-type]


def test_login_files_write_role_and_issued_credential(applier: Any, tmp_path: Path) -> None:
    applier.login_files("svc", issue=False)
    assert (tmp_path / "svc" / "role_id").read_text() == ROLE_ID_VALUE
    assert (tmp_path / "svc" / "secret_id").read_text() == ISSUED_VALUE
    assert applier.changes == ["role id file for svc", "issued login credential for svc"]


def test_valid_existing_credential_is_kept(applier: Any, tmp_path: Path) -> None:
    (tmp_path / "svc").mkdir()
    (tmp_path / "svc" / "secret_id").write_text("kept-value")
    applier.bao.lookup_valid = True
    applier.login_files("svc", issue=False)
    assert (tmp_path / "svc" / "secret_id").read_text() == "kept-value"
    assert "issued login credential for svc" not in applier.changes


def test_issue_flag_replaces_existing_credential(applier: Any, tmp_path: Path) -> None:
    (tmp_path / "svc").mkdir()
    (tmp_path / "svc" / "secret_id").write_text("old-value")
    applier.bao.lookup_valid = True
    applier.login_files("svc", issue=True)
    assert (tmp_path / "svc" / "secret_id").read_text() == ISSUED_VALUE


def test_generate_missing_covers_every_path_and_hides_values(
    applier: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    applier.generate_missing()
    written = applier.bao.kv_written
    assert set(written) == {f"secret/data/{p}" for p in apply.GENERATED_PATHS}
    assert all(written[f"secret/data/{p}"] for p in apply.GENERATED_PATHS)
    out = capsys.readouterr().out
    for payload in written.values():
        for value in payload.values():
            assert value not in out
    assert all("value not shown" in c for c in applier.changes)


def test_every_generated_path_has_a_generator() -> None:
    for path in apply.GENERATED_PATHS:
        assert apply._generate_value(path)


KEY_PATH = f"transit/keys/{apply.TRANSIT_KEY}"


def test_new_transit_key_is_derived_and_not_exportable(applier: Any) -> None:
    applier.transit_key()
    body = applier.bao.bodies[KEY_PATH]
    assert body["derived"] is True
    assert body["exportable"] is False
    assert body["type"] == "aes256-gcm96"


def test_existing_non_derived_transit_key_is_refused_with_a_clear_message(applier: Any) -> None:
    applier.bao.existing[KEY_PATH] = {"data": {"derived": False, "exportable": False}}
    with pytest.raises(apply.BaoError) as excinfo:
        applier.transit_key()
    message = str(excinfo.value)
    assert "not derived" in message
    assert "re-key" in message
    assert applier.changes == []


def test_existing_derived_transit_key_is_accepted(applier: Any) -> None:
    applier.bao.existing[KEY_PATH] = {
        "data": {"derived": True, "exportable": False, "auto_rotate_period": apply.YEAR_SECONDS}
    }
    applier.transit_key()
    assert applier.changes == []


def test_file_audit_device_is_enabled_once(applier: Any) -> None:
    applier.audit_device()
    body = applier.bao.bodies["sys/audit/file"]
    assert body is not None and body["type"] == "file"
    assert body["options"]["file_path"] == apply.DEFAULT_AUDIT_FILE
    assert applier.changes == [f"enabled file audit device ({apply.DEFAULT_AUDIT_FILE})"]

    applier.bao.audit_devices = {"file/": {"type": "file"}}
    applier.changes.clear()
    applier.audit_device()
    assert applier.changes == []
