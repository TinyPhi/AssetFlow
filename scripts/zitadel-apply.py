#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Zitadel as code for AssetFlow (P2-10, P2-11, §B5.5, §B11.2, decisions 51 and 52).

Applies deploy/zitadel/tofu (OpenTofu, official Zitadel provider) and keeps every credential
in OpenBao:

1. The tofu-admin machine key (written once by Zitadel setup into the zitadel_bootstrap
   volume) is moved into OpenBao ``secret/assetflow/zitadel/tofu-admin-key`` and deleted
   from the volume. Later runs read it from OpenBao into a temporary file for the run only.
2. ``tofu plan``; ``tofu apply`` only when the plan has changes ("No changes" otherwise). Apply
   runs with -parallelism=1: parallel writes to one Zitadel project can fail with an
   event-store conflict (duplicate key on events2_pkey).
3. The BFF client secret goes to ``secret/assetflow/idp`` and the automation machine key to
   ``secret/assetflow/zitadel/automation-key`` (only when they differ). Nothing is printed.
4. Prints the project id and the Zitadel organization id per AssetFlow organization slug.

Options:
    --check    offline: tofu init -backend=false and tofu validate only (no OpenBao, no Zitadel)

Environment (operator shell): BAO_ADDR, BAO_CACERT, BAO_TOKEN as for openbao-apply.py;
ZITADEL_DOMAIN, ZITADEL_EXTERNALPORT, ZITADEL_EXTERNALSECURE as for deploy/compose.full.yml;
TOFU_BIN (default: tofu, else terraform, on PATH; the run fails when neither is installed).
OpenTofu state stays local in deploy/zitadel/tofu and is git-ignored because it contains the
client secret and keys.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
TOFU_DIR = REPO_ROOT / "deploy" / "zitadel" / "tofu"
COMPOSE_FILE = REPO_ROOT / "deploy" / "compose.full.yml"
BOOTSTRAP_VOLUME = "assetflow_zitadel_bootstrap"  # compose project "assetflow"
BOOTSTRAP_KEY = "/bootstrap/tofu-admin-key.json"

TOFU_ADMIN_KEY_PATH = "assetflow/zitadel/tofu-admin-key"
AUTOMATION_KEY_PATH = "assetflow/zitadel/automation-key"
IDP_PATH = "assetflow/idp"


def _load_openbao_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "openbao_apply", Path(__file__).with_name("openbao-apply.py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tofu_bin() -> str | None:
    """OpenTofu (preferred) or Terraform: TOFU_BIN, else tofu, else terraform on PATH."""
    return os.environ.get("TOFU_BIN") or shutil.which("tofu") or shutil.which("terraform")


def _run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(TOFU_DIR), text=True, check=False, **kwargs)


def check_offline() -> int:
    tofu = _tofu_bin()
    if tofu:
        base = [tofu]
    elif shutil.which("docker"):
        # Official OpenTofu image; validate needs no network access to Zitadel.
        base = [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "tofu",
            "-v",
            f"{TOFU_DIR}:/t",
            "-w",
            "/t",
            "ghcr.io/opentofu/opentofu:1.12.6",
        ]
    else:
        print("error: neither tofu, terraform nor docker is available", file=sys.stderr)
        return 1
    env = dict(os.environ, MSYS_NO_PATHCONV="1")
    for args in (["init", "-backend=false", "-input=false"], ["validate"]):
        res = _run(base + args, env=env)
        if res.returncode != 0:
            return res.returncode
    return 0


def _kv_get(bao: Any, path: str) -> dict[str, Any] | None:
    payload = bao.get(f"secret/data/{path}")
    if payload is None:
        return None
    return (payload.get("data") or {}).get("data")


def _kv_put_if_different(bao: Any, path: str, data: dict[str, Any]) -> bool:
    if _kv_get(bao, path) == data:
        return False
    bao.ok("POST", f"secret/data/{path}", {"data": data})
    return True


def _import_bootstrap_key(bao: Any) -> str:
    """Move the tofu-admin key from the Zitadel bootstrap volume into OpenBao."""
    compose = [
        "docker",
        "compose",
        "-f",
        str(COMPOSE_FILE),
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "--user",
        "0",
        "--entrypoint",
        "sh",
        "-v",
        f"{BOOTSTRAP_VOLUME}:/bootstrap",
        "zitadel-secrets",
        "-c",
    ]
    env = dict(os.environ, MSYS_NO_PATHCONV="1")
    res = subprocess.run(
        compose + [f"cat {BOOTSTRAP_KEY}"], capture_output=True, text=True, env=env, check=False
    )
    if res.returncode != 0 or not res.stdout.strip().startswith("{"):
        raise RuntimeError(
            "tofu-admin key not in OpenBao and not in the zitadel_bootstrap volume; "
            "see docs/operations/zitadel.md (recover the tofu-admin key)"
        )
    key_json = res.stdout.strip()
    json.loads(key_json)  # must be valid JSON
    bao.ok(
        "POST",
        f"secret/data/{TOFU_ADMIN_KEY_PATH}",
        {"options": {"cas": 0}, "data": {"key_json": key_json}},
    )
    rm = subprocess.run(
        compose + [f"rm -f {BOOTSTRAP_KEY}"], capture_output=True, text=True, env=env, check=False
    )
    if rm.returncode != 0:
        print(f"warning: could not delete {BOOTSTRAP_KEY} from the bootstrap volume; delete it by hand")
    print("  moved the tofu-admin key from the bootstrap volume into OpenBao")
    return key_json


def apply() -> int:
    tofu = _tofu_bin()
    if not tofu:
        print(
            "error: neither OpenTofu (tofu) nor Terraform (terraform) is installed; install OpenTofu "
            "(https://opentofu.org/docs/intro/install/) or set TOFU_BIN. Nothing was applied.",
            file=sys.stderr,
        )
        return 1

    ob = _load_openbao_module()
    addr = os.environ.get("BAO_ADDR", "https://127.0.0.1:8200")
    cacert = os.environ.get("BAO_CACERT") or (str(ob.DEFAULT_CACERT) if ob.DEFAULT_CACERT.exists() else None)
    token = ob._token()
    if not token:
        print(
            "error: set BAO_TOKEN (operator token); see docs/operations/openbao.md",
            file=sys.stderr,
        )
        return 1
    bao = ob.Bao(addr, token, cacert)

    domain = os.environ.get("ZITADEL_DOMAIN", "localhost")
    port = os.environ.get("ZITADEL_EXTERNALPORT", "8081")
    secure = os.environ.get("ZITADEL_EXTERNALSECURE", "false").lower() == "true"
    issuer = f"{'https' if secure else 'http'}://{domain}" + ("" if port in ("80", "443") else f":{port}")

    try:
        stored = _kv_get(bao, TOFU_ADMIN_KEY_PATH)
        key_json = stored["key_json"] if stored else _import_bootstrap_key(bao)
    except (RuntimeError, ob.BaoError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    tmpdir = Path(tempfile.mkdtemp(prefix="assetflow-tofu-"))
    try:
        key_file = tmpdir / "tofu-admin-key.json"
        key_file.write_text(key_json, encoding="utf-8")
        os.chmod(key_file, 0o600)
        plan_file = tmpdir / "zitadel.tfplan"
        tf_vars = [
            f"-var=jwt_profile_file={key_file}",
            f"-var=zitadel_domain={domain}",
            f"-var=zitadel_port={port}",
            f"-var=zitadel_insecure={'false' if secure else 'true'}",
            f"-var=dev_mode={'false' if secure else 'true'}",
        ]

        print(f"==> OpenTofu in {TOFU_DIR} against {issuer}")
        if _run([tofu, "init", "-input=false"]).returncode != 0:
            return 1
        plan = _run(
            [
                tofu,
                "plan",
                "-input=false",
                "-detailed-exitcode",
                f"-out={plan_file}",
                *tf_vars,
            ]
        )
        if plan.returncode == 1:
            return 1
        if plan.returncode == 2:
            if _run([tofu, "apply", "-input=false", "-parallelism=1", str(plan_file)]).returncode != 0:
                return 1
        else:
            print("==> Zitadel: no changes.")

        out = _run([tofu, "output", "-json"], capture_output=True)
        if out.returncode != 0:
            print(out.stderr, file=sys.stderr)
            return 1
        outputs = {k: v["value"] for k, v in json.loads(out.stdout).items()}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    try:
        idp = {
            "issuer": issuer,
            "project_id": outputs["project_id"],
            "web_client_id": outputs["web_client_id"],
            "client_id": outputs["bff_client_id"],
            "client_secret": outputs["bff_client_secret"],
        }
        if _kv_put_if_different(bao, IDP_PATH, idp):
            print(f"  changed: secret/{IDP_PATH} (value not shown)")
        if _kv_put_if_different(bao, AUTOMATION_KEY_PATH, {"key_json": outputs["automation_key"]}):
            print(f"  changed: secret/{AUTOMATION_KEY_PATH} (value not shown)")
    except ob.BaoError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"==> project_id: {outputs['project_id']}")
    for slug, org_id in sorted(outputs.get("organization_ids", {}).items()):
        print(f"==> organization {slug}: idp_organization_id {org_id}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--check", action="store_true", help="offline validate only")
    args = parser.parse_args(argv)
    # Keep our lines in order with the OpenTofu output (subprocesses share the terminal).
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]
    return check_offline() if args.check else apply()


if __name__ == "__main__":
    sys.exit(main())
