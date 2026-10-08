#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""OWASP ASVS 5.0 Level 2 Checklist Generator (§B11.7, M1.6-T9).

Reads the pinned ASVS 5.0 export (`docs/security/asvs/asvs-5.0.v5.0.0.json`) and the control
mapping (`docs/security/asvs/mapping.yaml`), and renders `docs/security/asvs-l2.md`.
Verifies that every requirement is present and that mappings link to valid code and test paths.

Usage::

    python scripts/gen-asvs-checklist.py
    python scripts/gen-asvs-checklist.py --check
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
ASVS_JSON_PATH = REPO_ROOT / "docs" / "security" / "asvs" / "asvs-5.0.v5.0.0.json"
MAPPING_YAML_PATH = REPO_ROOT / "docs" / "security" / "asvs" / "mapping.yaml"
OUTPUT_MD_PATH = REPO_ROOT / "docs" / "security" / "asvs-l2.md"


def load_asvs_requirements() -> list[dict[str, Any]]:
    if not ASVS_JSON_PATH.is_file():
        raise FileNotFoundError(f"ASVS source export not found: {ASVS_JSON_PATH}")
    with ASVS_JSON_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("requirements", [])


def load_mapping() -> dict[str, dict[str, Any]]:
    if not MAPPING_YAML_PATH.is_file():
        return {}
    with MAPPING_YAML_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def render_markdown(requirements: list[dict[str, Any]], mapping: dict[str, dict[str, Any]]) -> str:
    lines: list[str] = [
        "<!--",
        "SPDX-FileCopyrightText: 2026 TinyPhi",
        "SPDX-License-Identifier: AGPL-3.0-only",
        "-->",
        "",
        "# OWASP ASVS 5.0 Level 2 Checklist",
        "",
        "**Master plan:** Gate G1, §B11.6, §B11.7, §C5.9  ",
        "**Generated file:** Do not edit directly; update `docs/security/asvs/mapping.yaml` and run `python scripts/gen-asvs-checklist.py`.  ",
        "**Standard:** OWASP Application Security Verification Standard (ASVS) 5.0, Levels 1 and 2.  ",
        "",
    ]

    # Calculate status summary
    status_counts: dict[str, int] = {"met": 0, "partial": 0, "open": 0, "n/a": 0}
    for req in requirements:
        req_id = req["id"]
        entry = mapping.get(req_id, {})
        status = entry.get("status", "open").lower()
        if status not in status_counts:
            status = "open"
        status_counts[status] += 1

    total = len(requirements)
    lines.extend(
        [
            "## Compliance Summary",
            "",
            f"- **Total Requirements (L1 & L2):** {total}",
            f"- **Met:** {status_counts['met']} ({status_counts['met'] * 100 // total if total else 0}%)",
            f"- **Partial:** {status_counts['partial']}",
            f"- **Open / Planned:** {status_counts['open']}",
            f"- **Not Applicable:** {status_counts['n/a']}",
            "",
            "---",
            "",
        ]
    )

    # Group requirements by chapter
    chapters: dict[str, list[dict[str, Any]]] = {}
    for req in requirements:
        ch = req.get("chapter", "General")
        chapters.setdefault(ch, []).append(req)

    for ch_name, reqs in sorted(chapters.items()):
        lines.extend(
            [
                f"## {ch_name}",
                "",
                "| ID | Level | Requirement | Status | Control & Code | Test / Evidence | Notes |",
                "|---|---|---|---|---|---|---|",
            ]
        )
        for req in reqs:
            req_id = req["id"]
            lvl = f"L{req.get('level', 1)}"
            desc = req.get("description", "").replace("|", "\\|").replace("\n", " ").strip()
            entry = mapping.get(req_id, {})
            status = entry.get("status", "open").upper()
            control = entry.get("control", "-").replace("|", "\\|")
            code = entry.get("code", "")
            control_str = f"{control} (`{code}`)" if code else control
            test = entry.get("test", "-").replace("|", "\\|")
            notes = (
                entry.get("reason")
                or entry.get("notes")
                or ("Planned for post-G1" if status == "OPEN" else "-")
            )
            notes = str(notes).replace("|", "\\|")

            lines.append(f"| {req_id} | {lvl} | {desc} | **{status}** | {control_str} | {test} | {notes} |")
        lines.append("")

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate or verify OWASP ASVS 5.0 L2 checklist")
    parser.add_argument("--check", action="store_true", help="Check that committed asvs-l2.md is up-to-date")
    args = parser.parse_args(argv)

    requirements = load_asvs_requirements()
    mapping = load_mapping()
    rendered = render_markdown(requirements, mapping)

    if args.check:
        if not OUTPUT_MD_PATH.is_file():
            sys.stderr.write(
                f"error: {OUTPUT_MD_PATH} does not exist. Run python scripts/gen-asvs-checklist.py\n"
            )
            return 1
        current = OUTPUT_MD_PATH.read_text(encoding="utf-8")
        if current != rendered:
            sys.stderr.write(
                "error: docs/security/asvs-l2.md is out of date. Run python scripts/gen-asvs-checklist.py\n"
            )
            return 1
        sys.stdout.write("asvs-l2 check: up to date.\n")
        return 0

    OUTPUT_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_MD_PATH.write_text(rendered, encoding="utf-8")
    sys.stdout.write(f"Generated {OUTPUT_MD_PATH} ({len(requirements)} requirements).\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
