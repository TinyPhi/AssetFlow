# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The channel credential path is write-only for the api and read-only for the worker (§B6.3 rule 1).

Reads the real `deploy/openbao/policies/*.hcl` and answers "may this role do X on this path"
the way OpenBao does when several stanzas match: the union of their capabilities, with `deny`
winning. The stricter union is used on purpose, so a broad `read` stanza that overlaps the channel
path would fail this test whatever OpenBao's priority rules decide.

Run: make test-scripts
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

POLICY_DIR = Path(__file__).resolve().parent.parent.parent / "deploy" / "openbao" / "policies"
STANZA = re.compile(r'path\s+"(?P<path>[^"]+)"\s*\{[^}]*?capabilities\s*=\s*\[(?P<caps>[^\]]*)\]', re.S)
ORG = "0190a000-0000-7000-8000-00000000000a"
CHANNEL = "0190a000-0000-7000-8000-00000000000b"
DATA = f"secret/data/assetflow/orgs/{ORG}/channels/{CHANNEL}"
METADATA = f"secret/metadata/assetflow/orgs/{ORG}/channels/{CHANNEL}"
LISTING = f"secret/metadata/assetflow/orgs/{ORG}/channels"


def _stanzas(role: str) -> list[tuple[str, set[str]]]:
    text = (POLICY_DIR / f"assetflow-{role}.hcl").read_text(encoding="utf-8")
    return [
        (m["path"], {c.strip().strip('"') for c in m["caps"].split(",") if c.strip()})
        for m in STANZA.finditer(text)
    ]


def _matches(pattern: str, path: str) -> bool:
    glob = pattern.endswith("*")
    pattern_parts = pattern.rstrip("*").split("/")
    path_parts = path.split("/")
    if glob:
        pattern_parts = pattern_parts[:-1] if pattern_parts[-1] == "" else pattern_parts
        head = path_parts[: len(pattern_parts)]
        return len(path_parts) >= len(pattern_parts) and all(p in ("+", h) for p, h in zip(pattern_parts, head, strict=True))
    return len(pattern_parts) == len(path_parts) and all(p in ("+", h) for p, h in zip(pattern_parts, path_parts, strict=True))


def capabilities(role: str, path: str) -> set[str]:
    granted: set[str] = set()
    for pattern, caps in _stanzas(role):
        if _matches(pattern, path):
            granted |= caps
    return set() if "deny" in granted else granted


def test_the_stanzas_are_found() -> None:
    assert any("channels" in pattern for pattern, _ in _stanzas("api"))
    assert any("channels" in pattern for pattern, _ in _stanzas("worker"))


@pytest.mark.parametrize("path", [DATA, METADATA, LISTING])
def test_the_api_can_never_read_or_list_a_channel_credential(path: str) -> None:
    assert not {"read", "list", "sudo"} & capabilities("api", path)


def test_the_api_can_write_and_remove_a_channel_credential() -> None:
    assert {"create", "update", "delete"} <= capabilities("api", DATA)
    assert "delete" in capabilities("api", METADATA)


def test_the_worker_can_read_but_never_write_a_channel_credential() -> None:
    caps = capabilities("worker", DATA)
    assert "read" in caps
    assert not {"create", "update", "delete", "patch"} & caps


@pytest.mark.parametrize("role", ["api", "worker"])
def test_the_migrator_credentials_stay_denied(role: str) -> None:
    assert capabilities(role, "secret/data/assetflow/migrator") == set()


@pytest.mark.parametrize("role", ["migrator", "postgres"])
def test_no_other_role_touches_the_channel_path(role: str) -> None:
    assert capabilities(role, DATA) == set()
