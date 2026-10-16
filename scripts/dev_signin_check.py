#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     "httpx==0.28.1",
#     "pyjwt[crypto]==2.15.1",
#     "cryptography==50.0.1",
# ]
# ///
"""Sign-in check of the local development stack (`dev_setup.py signin`, run by `make dev`).

Proves, against the running af-zitadel, that sign-in works end to end without printing a credential:

1. the OIDC discovery document of the public URL answers and its issuer equals that URL;
2. the web application's authorization request is accepted and redirects to the login screen;
3. the first admin (password generated into OpenBao) can open a Zitadel session, which is then
   deleted again.

Environment: BAO_ADDR, BAO_TOKEN, ZITADEL_BOOTSTRAP_URL (how this script reaches Zitadel),
ZITADEL_EXTERNALDOMAIN, ZITADEL_EXTERNALPORT (the public URL, sent as the Host header), APP_URL.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sys
import time

import httpx
import jwt

JWT_BEARER = "urn:ietf:params:oauth:grant-type:jwt-bearer"
API_SCOPE = "openid urn:zitadel:iam:org:project:id:zitadel:aud"


def report(ok: bool, message: str) -> bool:
    print(f"{'PASS' if ok else 'FAIL'}: {message}", flush=True)
    return ok


def kv(bao: httpx.Client, path: str) -> dict[str, str]:
    res = bao.get(f"/v1/secret/data/{path}")
    res.raise_for_status()
    return {str(k): str(v) for k, v in res.json()["data"]["data"].items()}


def main() -> int:
    bao = httpx.Client(
        base_url=os.environ.get("BAO_ADDR", "http://openbao:8200"),
        headers={"X-Vault-Token": os.environ["BAO_TOKEN"]},
        timeout=15,
    )
    domain = os.environ.get("ZITADEL_EXTERNALDOMAIN", "zitadel.localhost")
    port = os.environ.get("ZITADEL_EXTERNALPORT", "19081")
    public = f"http://{domain}:{port}"
    zitadel = httpx.Client(
        base_url=os.environ.get("ZITADEL_BOOTSTRAP_URL", f"http://zitadel:{port}"),
        headers={"Host": f"{domain}:{port}"},
        timeout=20,
        follow_redirects=False,
    )

    discovery = zitadel.get("/.well-known/openid-configuration")
    ok = report(
        discovery.status_code == 200 and discovery.json().get("issuer") == public,
        f"OIDC discovery answers and its issuer is {public}",
    )

    idp = kv(bao, "assetflow/idp")
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    app_url = os.environ.get("APP_URL", "http://localhost:18080").rstrip("/")
    authorize = zitadel.get(
        "/oauth/v2/authorize",
        params={
            "client_id": idp["web_client_id"],
            "response_type": "code",
            "scope": "openid profile email",
            "redirect_uri": f"{app_url}/auth/callback",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": secrets.token_urlsafe(8),
        },
    )
    ok &= report(
        authorize.status_code in (302, 303) and "/login" in authorize.headers.get("location", ""),
        "the web application's authorization request redirects to the Zitadel login screen",
    )

    key = json.loads(kv(bao, "assetflow/zitadel/bootstrap-key")["key_json"])
    now = int(time.time())
    assertion = jwt.encode(
        {"iss": key["userId"], "sub": key["userId"], "aud": public, "iat": now, "exp": now + 300},
        key["key"],
        algorithm="RS256",
        headers={"kid": key["keyId"]},
    )
    token = zitadel.post(
        "/oauth/v2/token", data={"grant_type": JWT_BEARER, "scope": API_SCOPE, "assertion": assertion}
    )
    if token.status_code != 200:
        report(False, f"service login with the bootstrap key failed (HTTP {token.status_code})")
        return 1
    auth = {"Authorization": f"Bearer {token.json()['access_token']}"}

    password = kv(bao, "assetflow/zitadel/admin")["initial_password"]
    session_ok = False
    for login_name in ("admin", f"admin@assetflow-platform.{domain}"):
        res = zitadel.post(
            "/v2/sessions",
            headers=auth,
            json={"checks": {"user": {"loginName": login_name}, "password": {"password": password}}},
        )
        if res.status_code in (200, 201):
            session_ok = True
            body = res.json()
            zitadel.request(
                "DELETE",
                f"/v2/sessions/{body['sessionId']}",
                headers=auth,
                json={},
            )
            break
    ok &= report(session_ok, "the first admin signs in (Zitadel session opened and closed)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
