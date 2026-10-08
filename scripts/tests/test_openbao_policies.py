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
STANZA = re.compile(r'path\s+"(?P<path>[^"]+)"\s*\{[^}]*?capabilities\s*=\s*\[(?P<caps>[^\]]*)\]', re.DOTALL)
ORG = "0190a000-0000-7000-8000-00000000000a"
CHANNEL = "0190a000-0000-7000-8000-00000000000b"
DATA = f"secret/data/assetflow/orgs/{ORG}/channels/{CHANNEL}"
METADATA = f"secret/metadata/assetflow/orgs/{ORG}/channels/{CHANNEL}"
LISTING = f"secret/metadata/assetflow/orgs/{ORG}/channels"


OPERATOR_POLICY = POLICY_DIR.parent / "operator" / "assetflow-operator.hcl"


def _stanzas(role: str) -> list[tuple[str, set[str]]]:
    file = OPERATOR_POLICY if role == "operator" else POLICY_DIR / f"assetflow-{role}.hcl"
    text = file.read_text(encoding="utf-8")
    return [
        (m["path"], {c.strip().strip('"') for c in m["caps"].split(",") if c.strip()})
        for m in STANZA.finditer(text)
    ]


def _matches(pattern: str, path: str) -> bool:
    """OpenBao path matching: `+` is one whole segment, a trailing `*` matches any suffix."""
    glob = pattern.endswith("*")
    body = pattern[:-1] if glob else pattern
    expression = "[^/]+".join(re.escape(part) for part in body.split("+"))
    return re.fullmatch(expression + (".*" if glob else ""), path) is not None


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
    assert {"create", "update", "patch", "delete"} <= capabilities("api", DATA)
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


# -- AF-029: narrow worker policy, database credentials split per role ----------------------------


def test_the_worker_has_no_broad_orgs_read() -> None:
    assert all(pattern != "secret/data/assetflow/orgs/*" for pattern, _ in _stanzas("worker"))
    other_org_path = f"secret/data/assetflow/orgs/{ORG}/smtp"
    assert capabilities("worker", other_org_path) == set()


def test_database_credentials_are_split_per_role() -> None:
    api, worker = "secret/data/assetflow/database/api", "secret/data/assetflow/database/worker"
    assert "read" in capabilities("api", api)
    assert "read" in capabilities("worker", worker)
    assert capabilities("api", worker) == set()
    assert capabilities("worker", api) == set()
    for role in ("api", "worker", "migrator", "postgres", "zitadel"):
        assert "read" not in capabilities(role, "secret/data/assetflow/database")


def test_the_migrator_reads_both_runtime_database_credentials() -> None:
    for name in ("api", "worker"):
        assert "read" in capabilities("migrator", f"secret/data/assetflow/database/{name}")


# -- AF-030: operator policy ----------------------------------------------------------------------


def test_the_operator_writes_only_assetflow_policies() -> None:
    assert "update" in capabilities("operator", "sys/policies/acl/assetflow-api")
    for name in ("default", "root", "zitadel", "other"):
        assert not {"create", "update", "delete", "patch"} & capabilities(
            "operator", f"sys/policies/acl/{name}"
        )


def test_every_shipped_policy_is_writable_by_the_operator() -> None:
    for file in sorted(POLICY_DIR.glob("*.hcl")) + [OPERATOR_POLICY]:
        assert "update" in capabilities("operator", f"sys/policies/acl/{file.stem}"), file.name


def test_the_operator_can_enable_the_audit_device() -> None:
    assert {"create", "update"} <= capabilities("operator", "sys/audit/file")
