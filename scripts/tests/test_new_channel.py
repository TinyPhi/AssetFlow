# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""scripts/new-channel.py: the channel scaffold (master plan §C6.7).

Run: make test-scripts
"""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "new-channel.py"
_spec = importlib.util.spec_from_file_location("new_channel", SCRIPT)
assert _spec is not None and _spec.loader is not None
new_channel: Any = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(new_channel)

REGISTRY = "backend/tests/contract/channels/channel_targets.py"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    registry = tmp_path / REGISTRY
    registry.parent.mkdir(parents=True)
    registry.write_text('TARGETS = {}\n\n\n@contract_target("inapp")\ndef _inapp(): ...\n', encoding="utf-8")
    return tmp_path


def test_it_creates_the_four_files_and_registers_the_channel(root: Path) -> None:
    written = new_channel.scaffold("demo-hook", root)
    expected = {
        "backend/app/channels/demo_hook.py",
        "backend/tests/contract/channels/test_demo_hook.py",
        "backend/tests/contract/channels/fixtures/demo_hook/ok.json",
        "docs/guides/channels/demo-hook.md",
        REGISTRY,
    }
    assert {p.as_posix() for p in written} == expected
    for path in expected - {REGISTRY}:
        assert (root / path).is_file()
    assert 'contract_target("demo-hook")' in (root / REGISTRY).read_text(encoding="utf-8")


def test_the_generated_python_is_valid_and_names_the_channel(root: Path) -> None:
    new_channel.scaffold("demo-hook", root)
    channel = (root / "backend/app/channels/demo_hook.py").read_text(encoding="utf-8")
    tree = ast.parse(channel)
    classes = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    assert classes == {"DemoHookSettings", "DemoHookChannel"}
    assert 'key: ClassVar[str] = "demo-hook"' in channel
    ast.parse((root / "backend/tests/contract/channels/test_demo_hook.py").read_text(encoding="utf-8"))
    ast.parse((root / REGISTRY).read_text(encoding="utf-8"))


def test_every_generated_file_has_an_spdx_header_and_no_placeholder_is_left(root: Path) -> None:
    new_channel.scaffold("demo-hook", root)
    for path in (
        "backend/app/channels/demo_hook.py",
        "backend/tests/contract/channels/test_demo_hook.py",
        "docs/guides/channels/demo-hook.md",
    ):
        text = (root / path).read_text(encoding="utf-8")
        assert "SPDX-License-Identifier: AGPL-3.0-only" in text
        assert (
            "@KEY@" not in text and "@CLASS@" not in text and "@MODULE@" not in text and "@TITLE@" not in text
        )
    assert json.loads((root / "backend/tests/contract/channels/fixtures/demo_hook/ok.json").read_text()) == {
        "ok": True
    }


@pytest.mark.parametrize("bad", ["", "Slack", "1slack", "a_b", "a b", "../x", "slack/"])
def test_a_bad_key_is_refused_and_nothing_is_written(root: Path, bad: str) -> None:
    with pytest.raises(ValueError, match="lower case"):
        new_channel.scaffold(bad, root)
    assert not (root / "backend/app").exists()


def test_an_existing_file_is_never_overwritten(root: Path) -> None:
    existing = root / "docs/guides/channels/demo-hook.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("mine", encoding="utf-8")
    with pytest.raises(FileExistsError):
        new_channel.scaffold("demo-hook", root)
    assert existing.read_text(encoding="utf-8") == "mine"
    assert not (root / "backend/app/channels/demo_hook.py").exists()  # nothing else was written either


def test_scaffolding_twice_is_refused(root: Path) -> None:
    new_channel.scaffold("demo-hook", root)
    with pytest.raises(FileExistsError):
        new_channel.scaffold("demo-hook", root)


def test_a_key_already_in_the_registry_is_refused(root: Path) -> None:
    with pytest.raises(FileExistsError, match="already registered"):
        new_channel.scaffold("inapp", root)


def test_a_missing_registry_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        new_channel.scaffold("demo-hook", tmp_path)


def test_the_command_line_reports_and_returns_status(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert new_channel.main(["demo-hook", "--root", str(root)]) == 0
    assert "demo_hook.py" in capsys.readouterr().out
    assert new_channel.main(["demo-hook", "--root", str(root)]) == 1
    assert "new-channel:" in capsys.readouterr().err
    assert new_channel.main(["Bad_Key", "--root", str(root)]) == 1
