#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Scaffold a notification channel (master plan §C6.7 step 2): `make new-channel name=<key>`.

Creates, from the templates in `scripts/templates/new-channel/`:

* `backend/app/channels/<module>.py`                         the channel class
* `backend/tests/contract/channels/test_<module>.py`         its specific tests
* `backend/tests/contract/channels/fixtures/<module>/ok.json` a recorded response to replay
* `docs/guides/channels/<key>.md`                            the setup guide

and registers the channel in `backend/tests/contract/channels/channel_targets.py`, so the shared
contract checks (schema export, write-only secrets, egress, health) run for it at once. It refuses
to overwrite anything. Standard library only.

Usage:
    python scripts/new-channel.py <key> [--root PATH]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = Path(__file__).resolve().parent / "templates" / "new-channel"
KEY_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
TARGETS_FILE = Path("backend/tests/contract/channels/channel_targets.py")


def names(key: str) -> dict[str, str]:
    """The placeholders every template uses."""
    module = key.replace("-", "_")
    return {
        "@KEY@": key,
        "@MODULE@": module,
        "@CLASS@": "".join(part.capitalize() for part in key.split("-")),
        "@TITLE@": " ".join(part.capitalize() for part in key.split("-")),
    }


def render(template: str, values: dict[str, str]) -> str:
    """Substitute the `@NAME@` placeholders."""
    text = (TEMPLATES / template).read_text(encoding="utf-8")
    for placeholder, value in values.items():
        text = text.replace(placeholder, value)
    return text


def targets(key: str) -> dict[Path, str]:
    """Relative path -> content of every file to create."""
    values = names(key)
    module = values["@MODULE@"]
    return {
        Path(f"backend/app/channels/{module}.py"): render("channel.py.tmpl", values),
        Path(f"backend/tests/contract/channels/test_{module}.py"): render("test_channel.py.tmpl", values),
        Path(f"backend/tests/contract/channels/fixtures/{module}/ok.json"): render("ok.json.tmpl", values),
        Path(f"docs/guides/channels/{key}.md"): render("guide.md.tmpl", values),
    }


def registration(key: str) -> str:
    """The block that registers the channel with the shared contract suite."""
    values = names(key)
    return (
        f"\n\n@contract_target(\"{key}\")\n"
        f"def _{values['@MODULE@']}() -> NotificationChannel:\n"
        f"    from app.channels.{values['@MODULE@']} import {values['@CLASS@']}Channel  # noqa: PLC0415\n\n"
        f"    return {values['@CLASS@']}Channel()\n"
    )


def scaffold(key: str, root: Path) -> list[Path]:
    """Create the files under `root`; returns what was written. Raises `FileExistsError` before writing."""
    if not KEY_PATTERN.match(key):
        raise ValueError("the channel key must be lower case letters, digits and hyphens, starting with a letter")
    files = targets(key)
    existing = [path for path in files if (root / path).exists()]
    if existing:
        raise FileExistsError(", ".join(str(p) for p in existing))
    registry = root / TARGETS_FILE
    if not registry.is_file():
        raise FileNotFoundError(f"{TARGETS_FILE} not found under {root}")
    if f'contract_target("{key}")' in registry.read_text(encoding="utf-8"):
        raise FileExistsError(f"{key!r} is already registered in {TARGETS_FILE}")
    for path, content in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    with registry.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(registration(key))
    return [*files, TARGETS_FILE]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("key", help="channel key: lower case letters, digits and hyphens")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="repository root (default: this one)")
    args = parser.parse_args(argv)
    try:
        written = scaffold(args.key, args.root)
    except (ValueError, FileExistsError, FileNotFoundError) as exc:
        sys.stderr.write(f"new-channel: {exc}\n")
        return 1
    for path in written:
        sys.stdout.write(f"  {path}\n")
    module = names(args.key)["@MODULE@"]
    sys.stdout.write(
        "\nNext (§C6.7): open a `channel.yml` issue first if you have not; implement `config_schema`, "
        "`egress_hosts`, `send` and `health` in\n"
        f"backend/app/channels/{module}.py (use only ctx.http and ctx.credentials); register the class in "
        "`default_registry()` in backend/app/channels/registry.py;\n"
        f"make `make test-contract` pass; add the display name `notification_channels.{args.key}.name` to "
        "frontend/src/lib/i18n/locales/en.json; fill in the guide.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
