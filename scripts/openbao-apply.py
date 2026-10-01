#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""OpenBao as code for AssetFlow (P2-08, §B11.4, §C5.5, decision 51).

Applies, through the OpenBao HTTP API, and only when something differs:

1. KV v2 at ``secret/`` and the transit engine at ``transit/``.
2. Transit key ``assetflow-fields`` (aes256-gcm96, not exportable, yearly auto-rotation).
3. ACL policies from ``deploy/openbao/policies/*.hcl`` (one AppRole each) and
   ``deploy/openbao/operator/*.hcl`` (operator policies, no AppRole).
4. AppRole auth and one role per service policy: periodic tokens, short-lived secret ids,
   secret ids and tokens bound to the compose network range.
5. Role id and secret id files in ``deploy/.secrets/<role>/`` (git-ignored), which compose
   mounts read-only into each container. A valid existing secret id is kept.

Running it twice reports "No changes" the second time. It never prints a secret value.

Options:
    --issue-secret-ids   issue fresh secret ids for every role (the start flow, §B11.4 step 2)
    --generate-missing   create random values for Zitadel and PostgreSQL secrets that do not
                         exist yet (check-and-set, so existing values are never overwritten)

Environment (operator shell, never a container):
    BAO_ADDR     default https://127.0.0.1:8200
    BAO_CACERT   default deploy/.secrets/openbao-tls/ca.pem
    BAO_TOKEN    operator token (or ~/.bao-token); the root token only for the first bootstrap
    ASSETFLOW_NET_CIDR   network range for bound CIDRs (default 172.28.0.0/24, "" disables)
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import ssl
import string
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
POLICY_DIR = REPO_ROOT / "deploy" / "openbao" / "policies"
OPERATOR_POLICY_DIR = REPO_ROOT / "deploy" / "openbao" / "operator"
CREDENTIALS_DIR = REPO_ROOT / "deploy" / ".secrets"
DEFAULT_CACERT = CREDENTIALS_DIR / "openbao-tls" / "ca.pem"

TRANSIT_KEY = "assetflow-fields"
YEAR_SECONDS = 365 * 24 * 3600

# AppRole settings (https://openbao.org/docs/auth/approle/). Periodic tokens renew for as
# long as the service renews them; the secret id is only needed at login and is short-lived.
ROLE_SETTINGS: dict[str, Any] = {
    "bind_secret_id": True,
    "secret_id_ttl": 24 * 3600,
    "secret_id_num_uses": 0,
    "token_period": 3600,
    "token_ttl": 0,
    "token_max_ttl": 0,
    "token_no_default_policy": False,
}

ALNUM = string.ascii_letters + string.digits


def _random(length: int, alphabet: str = ALNUM) -> str:
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _admin_password() -> str:
    # Satisfies Zitadel's default complexity policy (upper, lower, digit, symbol); 24 characters,
    # never $ or % (safe in compose and shell interpolation).
    core = _random(20)
    return (
        core
        + secrets.choice(string.ascii_uppercase)
        + secrets.choice(string.ascii_lowercase)
        + (secrets.choice(string.digits) + secrets.choice("!#+-.:=?@_"))
    )


# Values that --generate-missing may create. Everything else (SMTP, IdP client secret,
# channel secrets, database roles) is written by operators, the Zitadel bootstrap
# (scripts/bootstrap_zitadel.py) or migrations.
GENERATED_PATHS: tuple[str, ...] = (
    "assetflow/zitadel/masterkey",
    "assetflow/zitadel/database",
    "assetflow/zitadel/admin",
    "assetflow/postgres",
)


def _generate_value(path: str) -> dict[str, str]:
    """Fresh random KV payload for one of GENERATED_PATHS."""
    factories: dict[str, Any] = {
        "assetflow/zitadel/masterkey": lambda: {"value": _random(32)},
        "assetflow/zitadel/database": lambda: {
            "admin_password": _random(32),
            "user_password": _random(32),
        },
        "assetflow/zitadel/admin": lambda: {"initial_password": _admin_password()},
        "assetflow/postgres": lambda: {"superuser_password": _random(32)},
    }
    return factories[path]()


def _response_field(payload: dict[str, Any], field: str) -> str:
    """One string field from an OpenBao response's ``data`` object."""
    return str(payload["data"][field])


class BaoError(RuntimeError):
    pass


class Bao:
    def __init__(self, addr: str, token: str, cacert: str | None) -> None:
        self.addr = addr.rstrip("/")
        self.token = token
        self.ctx = ssl.create_default_context(cafile=cacert) if cacert else ssl.create_default_context()

    def call(self, method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"{self.addr}/v1/{path}", data=data, method=method)
        req.add_header("X-Vault-Token", self.token)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, context=self.ctx, timeout=15) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                payload = {"errors": [raw.decode(errors="replace")]}
            return exc.code, payload

    def ok(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        status, payload = self.call(method, path, body)
        if status >= 400:
            raise BaoError(f"{method} {path}: HTTP {status} {payload.get('errors', '')}")
        return payload

    def get(self, path: str) -> dict[str, Any] | None:
        status, payload = self.call("GET", path)
        if status == 404:
            return None
        if status >= 400:
            raise BaoError(f"GET {path}: HTTP {status} {payload.get('errors', '')}")
        return payload


class Applier:
    def __init__(self, bao: Bao, cidrs: list[str]) -> None:
        self.bao = bao
        self.cidrs = cidrs
        self.changes: list[str] = []

    def changed(self, what: str) -> None:
        self.changes.append(what)
        print(f"  changed: {what}")

    # -- engines ---------------------------------------------------------------------
    def mounts(self) -> None:
        payload = self.bao.ok("GET", "sys/mounts")
        mounts = payload.get("data", payload)
        kv = mounts.get("secret/")
        if kv is None:
            self.bao.ok("POST", "sys/mounts/secret", {"type": "kv", "options": {"version": "2"}})
            self.changed("enabled KV v2 at secret/")
        elif kv.get("type") != "kv" or str((kv.get("options") or {}).get("version")) != "2":
            raise BaoError("secret/ is mounted but is not KV version 2; fix it by hand first")
        transit = mounts.get("transit/")
        if transit is None:
            self.bao.ok("POST", "sys/mounts/transit", {"type": "transit"})
            self.changed("enabled transit at transit/")
        elif transit.get("type") != "transit":
            raise BaoError("transit/ is mounted but is not the transit engine")

    def transit_key(self) -> None:
        current = self.bao.get(f"transit/keys/{TRANSIT_KEY}")
        if current is None:
            self.bao.ok(
                "POST",
                f"transit/keys/{TRANSIT_KEY}",
                {
                    "type": "aes256-gcm96",
                    "exportable": False,
                    "auto_rotate_period": "8760h",
                },
            )
            self.changed(f"created transit key {TRANSIT_KEY}")
            return
        data = current.get("data", {})
        if data.get("exportable"):
            raise BaoError(f"transit key {TRANSIT_KEY} is exportable; that is not allowed")
        if int(data.get("auto_rotate_period") or 0) != YEAR_SECONDS or data.get("deletion_allowed"):
            self.bao.ok(
                "POST",
                f"transit/keys/{TRANSIT_KEY}/config",
                {"auto_rotate_period": "8760h", "deletion_allowed": False},
            )
            self.changed(f"configured transit key {TRANSIT_KEY}")

    # -- policies --------------------------------------------------------------------
    def policy(self, path: Path) -> None:
        name = path.stem
        text = path.read_text(encoding="utf-8")
        current = self.bao.get(f"sys/policies/acl/{name}")
        existing = (current or {}).get("data", {}).get("policy") if current else None
        if existing is not None and existing.strip() == text.strip():
            return
        self.bao.ok("PUT", f"sys/policies/acl/{name}", {"policy": text})
        self.changed(f"policy {name}")

    # -- AppRole ---------------------------------------------------------------------
    def approle_auth(self) -> None:
        payload = self.bao.ok("GET", "sys/auth")
        methods = payload.get("data", payload)
        if "approle/" not in methods:
            self.bao.ok("POST", "sys/auth/approle", {"type": "approle"})
            self.changed("enabled AppRole auth")

    def role(self, name: str) -> None:
        desired = dict(ROLE_SETTINGS)
        desired["token_policies"] = [name]
        desired["secret_id_bound_cidrs"] = list(self.cidrs)
        desired["token_bound_cidrs"] = list(self.cidrs)
        current = self.bao.get(f"auth/approle/role/{name}")
        data = (current or {}).get("data", {}) if current else None
        if data is not None and all(_same(data.get(k), v) for k, v in desired.items()):
            return
        self.bao.ok("POST", f"auth/approle/role/{name}", desired)
        self.changed(f"AppRole role {name}")

    def login_files(self, name: str, issue: bool) -> None:
        role_dir = CREDENTIALS_DIR / name
        role_dir.mkdir(parents=True, exist_ok=True)
        _chmod(role_dir, 0o700)
        identifier = _response_field(self.bao.ok("GET", f"auth/approle/role/{name}/role-id"), "role_id")
        if _write_if_different(role_dir / "role_id", identifier):
            self.changed(f"role id file for {name}")

        login_file = role_dir / "secret_id"
        valid = False
        if login_file.exists() and not issue:
            current = login_file.read_text(encoding="utf-8").strip()
            status, payload = self.bao.call(
                "POST",
                f"auth/approle/role/{name}/secret-id/lookup",
                {"secret_id": current},
            )
            valid = status == 200 and bool(payload.get("data"))
        if not valid:
            issued = self.bao.ok("POST", f"auth/approle/role/{name}/secret-id", {})
            _write_if_different(login_file, _response_field(issued, "secret_id"))
            self.changed(f"issued login credential for {name}")

    # -- generated values ----------------------------------------------------------
    def generate_missing(self) -> None:
        for path in GENERATED_PATHS:
            if self.bao.get(f"secret/metadata/{path}") is not None:
                continue
            status, payload = self.bao.call(
                "POST",
                f"secret/data/{path}",
                {"options": {"cas": 0}, "data": _generate_value(path)},
            )
            if status >= 400:
                raise BaoError(f"write secret/{path}: HTTP {status} {payload.get('errors', '')}")
            self.changed(f"generated kv entry {path} (value not shown)")


def _same(current: Any, desired: Any) -> bool:
    if isinstance(desired, list):
        return sorted(current or []) == sorted(desired)
    if isinstance(desired, bool):
        return bool(current) == desired
    if isinstance(desired, int):
        return int(current or 0) == desired
    return current == desired


def _chmod(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def _write_if_different(path: Path, value: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8").strip() == value:
        return False
    path.write_text(value, encoding="utf-8")
    # Read by the container user through a bind mount; the parent directory is 0700.
    _chmod(path, 0o644)
    return True


def _token() -> str:
    token = os.environ.get("BAO_TOKEN", "").strip()
    if not token:
        token_file = Path.home() / ".bao-token"
        if token_file.exists():
            token = token_file.read_text(encoding="utf-8").strip()
    return token


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--issue-secret-ids", action="store_true")
    parser.add_argument("--generate-missing", action="store_true")
    args = parser.parse_args(argv)

    service_policies = sorted(POLICY_DIR.glob("*.hcl"))
    operator_policies = sorted(OPERATOR_POLICY_DIR.glob("*.hcl"))
    if not service_policies:
        print(f"error: no policy files in {POLICY_DIR}", file=sys.stderr)
        return 1

    addr = os.environ.get("BAO_ADDR", "https://127.0.0.1:8200")
    cacert = os.environ.get("BAO_CACERT") or (str(DEFAULT_CACERT) if DEFAULT_CACERT.exists() else None)
    token = _token()
    if not token:
        print(
            "error: set BAO_TOKEN (operator token) in your shell; see docs/operations/openbao.md",
            file=sys.stderr,
        )
        return 1
    cidr_env = os.environ.get("ASSETFLOW_NET_CIDR", "172.28.0.0/24")
    cidrs = [c.strip() for c in cidr_env.split(",") if c.strip()]

    bao = Bao(addr, token, cacert)
    try:
        status, health = bao.call("GET", "sys/health")
    except (urllib.error.URLError, OSError) as exc:
        print(f"error: OpenBao not reachable at {addr}: {exc}", file=sys.stderr)
        return 1
    if health.get("sealed", True) or not health.get("initialized", False):
        print(
            f"error: OpenBao is not initialized or is sealed (HTTP {status}); run the unseal runbook",
            file=sys.stderr,
        )
        return 1

    applier = Applier(bao, cidrs)
    try:
        self_info = bao.ok("GET", "auth/token/lookup-self").get("data", {})
        if "root" in (self_info.get("policies") or []):
            print(
                "warning: using the root token. After this bootstrap run, create an operator token "
                "(policy assetflow-operator) and revoke the root token (docs/operations/openbao.md)."
            )
        print(f"==> OpenBao at {addr}")
        applier.mounts()
        applier.transit_key()
        for path in operator_policies + service_policies:
            applier.policy(path)
        applier.approle_auth()
        for path in service_policies:
            applier.role(path.stem)
            applier.login_files(path.stem, args.issue_secret_ids)
        if args.generate_missing:
            applier.generate_missing()
    except BaoError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if applier.changes:
        print(f"==> Applied {len(applier.changes)} change(s).")
    else:
        print("==> No changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
