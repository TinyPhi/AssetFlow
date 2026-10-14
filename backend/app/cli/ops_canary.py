# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""``assetflow ops canary``: field encryption restore verification canary (§B13.5, M1.6-T9).

Stores and verifies a canary field encrypted with the secrets provider's transit/field key.
Used during bootstrap and post-restore smoke testing to prove that secret keys and database
contents match and field decryption succeeds.

Usage::

    uv run python -m app.cli.ops_canary write [--org-slug example-alpha]
    uv run python -m app.cli.ops_canary check [--org-slug example-alpha]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from typing import Any, TextIO
from uuid import UUID

from app.core.config import load_config
from app.core.db import close_pool, init_pool
from app.providers.registry import ProviderRegistry

DEFAULT_CANARY_PLAINTEXT = "assetflow-restore-verification-canary-token-2026"


async def async_write_canary(
    org_slug: str, plaintext: str, out: TextIO = sys.stdout, err: TextIO = sys.stderr
) -> int:
    config = load_config()
    registry = ProviderRegistry.from_config(config)
    pool = await init_pool(config.database, "api", registry.resolve_secret)
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, settings FROM public.organizations WHERE slug = $1",
                org_slug,
            )
            if not row:
                err.write(f"error: organization '{org_slug}' not found\n")
                return 1

            org_id: UUID = row["id"]
            current_settings: dict[str, Any] = (
                json.loads(row["settings"]) if isinstance(row["settings"], str) else (row["settings"] or {})
            )

            context = str(org_id)
            ciphertext = await registry.secrets.encrypt(context, plaintext)
            expected_hash = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()

            current_settings["restore_canary"] = {
                "ciphertext": ciphertext,
                "sha256": expected_hash,
            }

            await conn.execute(
                "UPDATE public.organizations SET settings = $1 WHERE id = $2",
                json.dumps(current_settings),
                org_id,
            )
            out.write(f"Canary written successfully for organization '{org_slug}' ({org_id}).\n")
            return 0
    finally:
        await close_pool(pool)


async def async_check_canary(org_slug: str, out: TextIO = sys.stdout, err: TextIO = sys.stderr) -> int:
    config = load_config()
    registry = ProviderRegistry.from_config(config)
    pool = await init_pool(config.database, "api", registry.resolve_secret)
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, settings FROM public.organizations WHERE slug = $1",
                org_slug,
            )
            if not row:
                err.write(f"error: organization '{org_slug}' not found\n")
                return 1

            org_id: UUID = row["id"]
            settings: dict[str, Any] = (
                json.loads(row["settings"]) if isinstance(row["settings"], str) else (row["settings"] or {})
            )
            canary_info = settings.get("restore_canary")
            if not canary_info:
                err.write(f"error: no restore_canary found in settings for '{org_slug}'\n")
                return 1

            ciphertext = canary_info.get("ciphertext")
            expected_hash = canary_info.get("sha256")
            if not ciphertext or not expected_hash:
                err.write(f"error: invalid canary record in settings for '{org_slug}'\n")
                return 1

            context = str(org_id)
            try:
                decrypted = await registry.secrets.decrypt(context, ciphertext)
            except (OSError, RuntimeError, ValueError) as exc:
                err.write(f"error: failed to decrypt canary field: {exc}\n")
                return 1

            actual_hash = hashlib.sha256(decrypted.encode("utf-8")).hexdigest()
            if actual_hash != expected_hash:
                err.write("error: canary hash mismatch! Decrypted value differs from expected.\n")
                return 1

            out.write(f"Canary check OK: field decrypted successfully for '{org_slug}', hash matches.\n")
            return 0
    finally:
        await close_pool(pool)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AssetFlow restore canary management")
    subparsers = parser.add_subparsers(dest="command", required=True)

    write_parser = subparsers.add_parser("write", help="Write encrypted canary to organization settings")
    write_parser.add_argument(
        "--org-slug", default="example-alpha", help="Organization slug (default: example-alpha)"
    )
    write_parser.add_argument(
        "--plaintext", default=DEFAULT_CANARY_PLAINTEXT, help="Canary string to encrypt"
    )

    check_parser = subparsers.add_parser("check", help="Verify and decrypt canary from organization settings")
    check_parser.add_argument(
        "--org-slug", default="example-alpha", help="Organization slug (default: example-alpha)"
    )

    args = parser.parse_args(argv)

    if args.command == "write":
        return asyncio.run(async_write_canary(args.org_slug, args.plaintext))
    if args.command == "check":
        return asyncio.run(async_check_canary(args.org_slug))
    return 1


if __name__ == "__main__":
    sys.exit(main())
