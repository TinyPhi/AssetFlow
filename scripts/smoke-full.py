#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Smoke test for the AssetFlow full profile (P2-12, §B11.4 startup flow, M1.6-T8).

Checks, in startup order, and exits non-zero on the first failed group:

1. OpenBao is initialized and unsealed (``/v1/sys/health`` over TLS).
2. Zitadel is healthy (``/debug/healthz``) and its issuer matches the configured public URL.
3. AssetFlow API ``/healthz`` answers 200 and every provider it reports is healthy.
4. No running container of the stack carries a credential in its environment
   (only ``*_FILE`` locations and non-secret settings are allowed).

Options:
    --skip-api        skip check 3 (before the API image exists)
    --expect-sealed   instead of the checks above, verify the sealed-state behaviour: OpenBao
                      reports sealed and the api container stopped with
                      platform.secrets_unavailable in its log

Environment: OPENBAO_HOST_PORT (8200), BAO_CACERT (deploy/.secrets/openbao-tls/ca.pem),
ZITADEL_DOMAIN (localhost), ZITADEL_EXTERNALPORT (8081), ZITADEL_EXTERNALSECURE (false),
API_HOST_PORT (8080).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = REPO_ROOT / "deploy" / "compose.full.yml"
DEFAULT_CACERT = REPO_ROOT / "deploy" / ".secrets" / "openbao-tls" / "ca.pem"

# Environment names that would carry a credential value (the *_FILE variants are fine).
SECRET_ENV = re.compile(r"(PASSWORD|SECRET|TOKEN|MASTERKEY|PRIVATE_KEY|ROLE_ID|SECRET_ID)$", re.IGNORECASE)


def fetch(url: str, ctx: ssl.SSLContext | None = None) -> tuple[int, bytes]:
    handlers: list[urllib.request.BaseHandler] = [urllib.request.ProxyHandler({})]
    if ctx is not None:
        handlers.append(urllib.request.HTTPSHandler(context=ctx))
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, headers={"User-Agent": "assetflow-smoke/1.0"})
    try:
        with opener.open(req, timeout=10) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def report(ok: bool, message: str) -> bool:
    print(f"{'PASS' if ok else 'FAIL'}: {message}")
    return ok


def openbao_health() -> dict | None:
    port = os.environ.get("OPENBAO_HOST_PORT", "8200")
    cacert = os.environ.get("BAO_CACERT") or str(DEFAULT_CACERT)
    ctx = ssl.create_default_context(cafile=cacert) if Path(cacert).exists() else ssl.create_default_context()
    try:
        status, body = fetch(f"https://127.0.0.1:{port}/v1/sys/health?sealedcode=503&uninitcode=501", ctx)
    except (urllib.error.URLError, OSError) as exc:
        report(False, f"OpenBao unreachable on 127.0.0.1:{port}: {exc}")
        return None
    try:
        health = json.loads(body or b"{}")
    except json.JSONDecodeError:
        health = {}
    health["_status"] = status
    return health


def check_openbao() -> bool:
    health = openbao_health()
    if health is None:
        return False
    ok = health["_status"] == 200 and health.get("initialized") and not health.get("sealed", True)
    return report(
        bool(ok),
        f"OpenBao initialized={health.get('initialized')} sealed={health.get('sealed')}",
    )


def check_zitadel() -> bool:
    domain = os.environ.get("ZITADEL_DOMAIN", "localhost")
    port = os.environ.get("ZITADEL_EXTERNALPORT", "8081")
    secure = os.environ.get("ZITADEL_EXTERNALSECURE", "false").lower() == "true"
    base = f"{'https' if secure else 'http'}://{domain}" + ("" if port in ("80", "443") else f":{port}")
    try:
        status, body = fetch(f"{base}/debug/healthz")
        ok = report(status == 200, f"Zitadel {base}/debug/healthz -> {status} {body[:20]!r}")
        status, body = fetch(f"{base}/.well-known/openid-configuration")
        issuer = json.loads(body or b"{}").get("issuer") if status == 200 else None
        return report(ok and issuer == base, f"Zitadel issuer {issuer!r} matches {base!r}") and ok
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        return report(False, f"Zitadel unreachable at {base}: {exc}")


def check_api() -> bool:
    port = os.environ.get("API_HOST_PORT", "8080")
    url = f"http://127.0.0.1:{port}/healthz"
    try:
        status, body = fetch(url)
    except (urllib.error.URLError, OSError) as exc:
        return report(False, f"AssetFlow API unreachable at {url}: {exc}")
    if not report(status == 200, f"AssetFlow API {url} -> {status}"):
        return False
    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError:
        return report(False, "AssetFlow API /healthz did not return JSON")
    providers = payload.get("providers") or {}
    bad = {
        name: p
        for name, p in providers.items()
        if str((p or {}).get("status", p)).lower() not in ("ok", "healthy")
    }
    return report(
        not bad,
        f"AssetFlow providers healthy ({', '.join(sorted(providers)) or 'none reported'})"
        + (f"; unhealthy: {sorted(bad)}" if bad else ""),
    )


def compose(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def check_no_env_credentials() -> bool:
    res = compose("ps", "-q")
    ids = res.stdout.split()
    if res.returncode != 0 or not ids:
        return report(False, "no running containers found for deploy/compose.full.yml")
    inspect = subprocess.run(["docker", "inspect", *ids], capture_output=True, text=True, check=False)
    offenders: list[str] = []
    for container in json.loads(inspect.stdout or "[]"):
        name = container.get("Name", "").lstrip("/")
        for entry in container.get("Config", {}).get("Env") or []:
            key = entry.split("=", 1)[0]
            if SECRET_ENV.search(key):
                offenders.append(f"{name}:{key}")
    return report(
        not offenders,
        "no credentials in container environments"
        + (f"; found {offenders}" if offenders else f" ({len(ids)} containers)"),
    )


def check_sealed_refusal() -> bool:
    health = openbao_health()
    sealed = bool(health) and health.get("sealed") is True
    ok = report(
        sealed,
        f"OpenBao reports sealed={None if health is None else health.get('sealed')}",
    )
    logs = compose("logs", "--no-color", "--tail", "200", "api")
    refused = "platform.secrets_unavailable" in (logs.stdout + logs.stderr)
    return report(ok and refused, "api boot stopped with platform.secrets_unavailable") and ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--skip-api", action="store_true")
    parser.add_argument("--expect-sealed", action="store_true")
    args = parser.parse_args(argv)

    print("==> AssetFlow full profile smoke test")
    if args.expect_sealed:
        return 0 if check_sealed_refusal() else 1
    checks = [check_openbao, check_zitadel]
    if not args.skip_api:
        checks.append(check_api)
    checks.append(check_no_env_credentials)
    for check in checks:
        if not check():
            print("==> Smoke test FAILED")
            return 1
    print("==> Smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
