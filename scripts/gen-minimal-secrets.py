# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Bootstrap local development secrets for the AssetFlow minimal profile (§B13.1).

Creates the git-ignored file secrets expected by FileSecretsProvider and the minimal
database container under .secrets/ (or the directory given by ASSETFLOW_SECRETS_DIR).
Never overwrites existing secret files unless --force is passed.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path

ROLES = ("api", "worker", "migrator")


def generate_dev_secrets(target_dir: Path, *, force: bool = False) -> None:
    """Generate dev secrets in target_dir."""
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        target_dir.chmod(0o700)
    except OSError:
        pass

    db_dir = target_dir / "database"
    db_dir.mkdir(parents=True, exist_ok=True)
    try:
        db_dir.chmod(0o700)
    except OSError:
        pass

    transit_dir = target_dir / "transit"
    transit_dir.mkdir(parents=True, exist_ok=True)
    try:
        transit_dir.chmod(0o700)
    except OSError:
        pass

    # Postgres superuser password
    pg_pw_file = db_dir / "postgres" / "password"
    pg_pw_file.parent.mkdir(parents=True, exist_ok=True)
    if force or not pg_pw_file.is_file():
        pw = secrets.token_urlsafe(24)
        pg_pw_file.write_text(pw, encoding="utf-8")
        try:
            pg_pw_file.chmod(0o600)
        except OSError:
            pass

    # Database role passwords
    for role in ROLES:
        role_dir = db_dir / role
        role_dir.mkdir(parents=True, exist_ok=True)
        try:
            role_dir.chmod(0o700)
        except OSError:
            pass

        pw_file = role_dir / "password"
        json_file = db_dir / f"{role}.json"

        if force or not pw_file.is_file():
            pw = secrets.token_urlsafe(24)
            pw_file.write_text(pw, encoding="utf-8")
            try:
                pw_file.chmod(0o600)
            except OSError:
                pass
        else:
            pw = pw_file.read_text(encoding="utf-8").strip()

        if force or not json_file.is_file():
            json_file.write_text(json.dumps({"password": pw}), encoding="utf-8")
            try:
                json_file.chmod(0o600)
            except OSError:
                pass

    # Transit AES-256-GCM encryption key (32 bytes)
    key_file = transit_dir / "file.key"
    if force or not key_file.is_file():
        key_file.write_bytes(secrets.token_bytes(32))
        try:
            key_file.chmod(0o600)
        except OSError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap minimal dev file secrets.")
    parser.add_argument(
        "--dir",
        default=os.environ.get("ASSETFLOW_SECRETS_DIR", ".secrets"),
        help="Directory to write secrets into (default: .secrets)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing secret files",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    target = Path(args.dir)
    if not target.is_absolute():
        target = repo_root / target

    generate_dev_secrets(target, force=args.force)
    sys.stdout.write(f"dev secrets ready: {target}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
