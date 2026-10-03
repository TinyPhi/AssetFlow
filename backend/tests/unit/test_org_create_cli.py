# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""`app.cli.org_create` argument validation (no database; M1.4-T2)."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from app.cli.org_create import OrgCreateError, _build_parser, _load_organization_file, _resolve_args


def _args(**overrides: object) -> argparse.Namespace:
    base = {
        "slug": "example-alpha",
        "admin_email": "admin@example-alpha.test",
        "idp_org": "idp-123",
        "name": None,
        "domain_key": "generic",
        "organizations_dir": Path("does-not-exist"),
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def test_resolve_args_accepts_a_valid_slug_and_email() -> None:
    name, email, idp_org = _resolve_args(_args(name="Example Alpha"))
    assert (name, email, idp_org) == ("Example Alpha", "admin@example-alpha.test", "idp-123")


@pytest.mark.parametrize("slug", ["Example-Alpha", "example_alpha", "-example", "example-", "ex ample", ""])
def test_resolve_args_rejects_an_invalid_slug(slug: str) -> None:
    with pytest.raises(OrgCreateError, match="--slug"):
        _resolve_args(_args(slug=slug, name="X"))


@pytest.mark.parametrize("email", ["not-an-email", "a@b", "@example.test", ""])
def test_resolve_args_rejects_an_invalid_email(email: str) -> None:
    with pytest.raises(OrgCreateError, match="--admin-email"):
        _resolve_args(_args(admin_email=email, name="X"))


def test_resolve_args_requires_idp_org() -> None:
    with pytest.raises(OrgCreateError, match="--idp-org"):
        _resolve_args(_args(idp_org="", name="X"))


def test_resolve_args_requires_a_name_with_no_organization_file() -> None:
    with pytest.raises(OrgCreateError, match="--name"):
        _resolve_args(_args(name=None))


def test_load_organization_file_supplies_the_name(tmp_path: Path) -> None:
    (tmp_path / "example-alpha.yaml").write_text(
        "slug: example-alpha\nname: Example Alpha\n", encoding="utf-8"
    )
    name, _, _ = _resolve_args(_args(name=None, organizations_dir=tmp_path))
    assert name == "Example Alpha"


def test_load_organization_file_rejects_a_mismatched_slug(tmp_path: Path) -> None:
    (tmp_path / "example-alpha.yaml").write_text("slug: other\nname: X\n", encoding="utf-8")
    with pytest.raises(OrgCreateError, match="slug must equal the file name"):
        _load_organization_file(tmp_path, "example-alpha")


def test_cli_name_overrides_the_organization_file(tmp_path: Path) -> None:
    (tmp_path / "example-alpha.yaml").write_text("slug: example-alpha\nname: From File\n", encoding="utf-8")
    name, _, _ = _resolve_args(_args(name="From CLI", organizations_dir=tmp_path))
    assert name == "From CLI"


def test_parser_requires_slug_admin_email_and_idp_org() -> None:
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])
    args = parser.parse_args(
        ["--slug", "example-alpha", "--admin-email", "admin@example-alpha.test", "--idp-org", "idp-1"]
    )
    assert (args.slug, args.admin_email, args.idp_org) == (
        "example-alpha",
        "admin@example-alpha.test",
        "idp-1",
    )
