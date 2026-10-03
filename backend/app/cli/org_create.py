# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""``assetflow org create``: one organization and its invited first admin (§B5.5, M1.4-T2).

Runs as a platform-level operator command, not a tenant request: it connects with the `api`
database role (the only role with INSERT on `organizations`, see migration 0007) but outside any
HTTP handler, request context or scope resolver. A Zitadel organization is created separately by
`make zitadel-apply` (``scripts/bootstrap_zitadel.py``, already idempotent); this command only
records the resulting ``--idp-org`` id, as documented in ``config/organizations/<slug>.yaml``.

Usage::

    uv run python -m app.cli.org_create --slug example-alpha --admin-email admin@example.test \\
        --idp-org <zitadel organization id>

A second run with the same ``--slug`` prints "no changes" and exits 0.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from app.core.config import ConfigError, load_config
from app.core.db import close_pool, init_pool
from app.modules.organization.provisioning import DEFAULT_POLICY, PROVISIONING_POLICIES
from app.modules.organization.service import create_organization
from app.providers.registry import ProviderRegistry

_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DEFAULT_ORGANIZATIONS_DIR = Path(__file__).resolve().parents[3] / "config" / "organizations"


class OrgCreateError(ValueError):
    """An invalid argument or organization file; the CLI prints it and exits 1."""


def _load_organization_file(organizations_dir: Path, slug: str) -> dict[str, Any]:
    path = organizations_dir / f"{slug}.yaml"
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise OrgCreateError(f"{path}: top level must be a mapping")
    if data.get("slug") != slug:
        raise OrgCreateError(f"{path}: slug must equal the file name ({slug})")
    return data


def _resolve_args(args: argparse.Namespace) -> tuple[str, str, str, str]:
    """Validate and merge CLI args with the optional organization file.

    Returns (name, email, idp_org, provisioning_policy).
    """
    if not _SLUG_RE.match(args.slug):
        raise OrgCreateError(
            f"invalid --slug {args.slug!r}: must be lowercase letters, digits and single hyphens"
        )
    if not _EMAIL_RE.match(args.admin_email):
        raise OrgCreateError(f"invalid --admin-email {args.admin_email!r}")
    org_file = _load_organization_file(args.organizations_dir, args.slug)
    name = args.name or org_file.get("name")
    if not name:
        raise OrgCreateError("--name is required (no config/organizations/<slug>.yaml name to fall back to)")
    if not args.idp_org:
        raise OrgCreateError(
            "--idp-org is required: run `make zitadel-apply` first and pass the organization id it prints"
        )
    policy = args.provisioning or org_file.get("provisioning") or DEFAULT_POLICY
    if policy not in PROVISIONING_POLICIES:
        raise OrgCreateError(
            f"invalid provisioning policy {policy!r}: must be one of {', '.join(PROVISIONING_POLICIES)}"
        )
    return str(name), args.admin_email, args.idp_org, policy


async def run(args: argparse.Namespace, *, out: Any = sys.stdout) -> int:
    try:
        name, admin_email, idp_org, policy = _resolve_args(args)
    except OrgCreateError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1

    registry = ProviderRegistry.from_config(cfg)
    pool = await init_pool(cfg.database, "api", registry.resolve_secret)
    try:
        result = await create_organization(
            pool,
            slug=args.slug,
            name=name,
            admin_email=admin_email,
            idp_organization_id=idp_org,
            domain_key=args.domain_key,
            settings={"provisioning": policy},
        )
    finally:
        await close_pool(pool)

    if not result.created:
        out.write(f"organization {args.slug!r} already exists (id={result.organization_id}); no changes\n")
        return 0
    out.write(
        f"created organization {args.slug!r} (id={result.organization_id}), "
        f"invited admin {admin_email!r} (member id={result.admin_member_id})\n"
    )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--slug", required=True, help="organization slug, e.g. example-alpha")
    parser.add_argument("--admin-email", required=True, help="first admin's email (invite only)")
    parser.add_argument("--idp-org", required=True, help="Zitadel org id (from `make zitadel-apply`)")
    parser.add_argument("--name", help="organization display name (else read from the organization file)")
    parser.add_argument(
        "--provisioning",
        choices=PROVISIONING_POLICIES,
        help="sign-in policy (else the organization file's `provisioning`, else invite_only)",
    )
    parser.add_argument("--domain-key", default="generic", help="config/domains key (default: generic)")
    parser.add_argument("--config", help="path to assetflow.yaml (else ASSETFLOW_CONFIG or the default)")
    parser.add_argument(
        "--organizations-dir",
        type=Path,
        default=DEFAULT_ORGANIZATIONS_DIR,
        help="directory of <slug>.yaml organization files (default: config/organizations)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    import asyncio  # noqa: PLC0415 - keep the import-time surface of this module minimal

    args = _build_parser().parse_args(argv)
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
