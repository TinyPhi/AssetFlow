#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     "httpx==0.28.1",
#     "pyyaml==6.0.3",
#     "pyjwt[crypto]==2.15.1",
#     "cryptography==50.0.1",
# ]
# ///
"""Idempotent Zitadel bootstrap for AssetFlow (§B5.5, §B11.2, §B11.4, decisions 51 and 52).

Configures a self-hosted Zitadel instance through its official REST APIs (Management v1,
Admin v1, v2 organizations). Every step searches first and creates only what is missing;
"already exists" (HTTP 409) counts as success and settings are re-applied with PUT. A second
run reports "No changes".

Steps, in order:
 1. wait until Zitadel is ready (``/debug/ready``);
 2. authenticate: the stored bootstrap key (JWT profile grant), else the key (or PAT) that
    Zitadel wrote for the first-instance machine user (``FirstInstance.Org.Machine``). A key
    from the volume is rotated at once: a new key is stored, the old key is revoked in
    Zitadel and the file is deleted;
 3. project ``AssetFlow`` (role assertion, role check, project check) in the platform org;
 4. project roles (``rbac.roles`` of ``config/assetflow.yaml``, else the §B7.2 defaults);
 5. ``assetflow-web``: public user-agent client, code + PKCE, no secret, JWT access tokens;
 6. ``assetflow-bff``: confidential web client (client secret basic, refresh tokens);
 7. ``assetflow-introspection``: API application with a client secret (token introspection);
 8. ``assetflow-automation``: machine user (IAM_ORG_MANAGER) with a JSON key, for the
    runtime Management API calls (``assetflow org create --create-idp-org``, §B5.7);
 9. one Zitadel organization per ``config/organizations/<slug>.yaml`` plus a project grant
    with its ``idp.granted_roles``; the organization id is ``idp_organization_id``;
10. production only: strict login policy (MFA forced, self-registration off);
11. results are written to the secret store and printed (never the secret values).

Secret store:
    development (default)       ``.env.local`` in the repository root (git-ignored)
    ASSETFLOW_ENV=production    OpenBao KV ``secret/assetflow/idp`` and
                                ``secret/assetflow/zitadel/*`` (BAO_ADDR, BAO_CACERT,
                                BAO_TOKEN = operator token); never a file

Commands:
    apply [--dry-run]   the steps above (default command); --dry-run only reads and prints
                        the planned actions
    init-env            development only: create the local secrets (masterkey, admin and
                        database passwords) in .env.local when missing, and refuse to go on
                        when the Zitadel volume was created with another masterkey

Environment: ZITADEL_BOOTSTRAP_URL (how this script reaches Zitadel, default
http://localhost:<port>), ZITADEL_DOMAIN, ZITADEL_EXTERNALPORT, ZITADEL_EXTERNALSECURE (the
public URL; sent as the Host header), APP_URL, API_URL (redirect URIs), ASSETFLOW_ROOT,
ASSETFLOW_ENV_FILE, ZITADEL_FIRSTINSTANCE_KEY_FILE, ZITADEL_FIRSTINSTANCE_PAT_FILE,
ZITADEL_ADMIN_USERNAME. See docs/operations/zitadel.md.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import json
import os
import secrets
import string
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import jwt
import yaml

# ---------------------------------------------------------------- constants

PROJECT_NAME = "AssetFlow"
WEB_APP = "assetflow-web"
BFF_APP = "assetflow-bff"
INTROSPECTION_APP = "assetflow-introspection"
AUTOMATION_USER = "assetflow-automation"
AUTOMATION_ROLES = ["IAM_ORG_MANAGER"]
KEY_EXPIRATION = "2030-01-01T00:00:00Z"

# Default project roles, master plan §B7.2 (used when config/assetflow.yaml has no rbac.roles).
DEFAULT_ROLES: dict[str, str] = {
    "viewer": "Viewer",
    "technician": "Technician",
    "team_lead": "Team lead",
    "asset_manager": "Asset manager",
    "maintenance_planner": "Maintenance planner",
    "org_unit_manager": "Org unit manager",
    "admin": "Organization admin",
}
ROLE_GROUP = "assetflow"

# Result names (the .env.local keys). JSON keys are base64 in .env.local (single line).
KEY_FIELDS = frozenset({"ZITADEL_SERVICE_ACCOUNT_KEY", "ZITADEL_BOOTSTRAP_KEY"})
SECRET_FIELDS = KEY_FIELDS | {"ZITADEL_BFF_CLIENT_SECRET", "ZITADEL_INTROSPECTION_CLIENT_SECRET"}

# Where each result lives in OpenBao (KV v2 under secret/). None = the whole map.
OPENBAO_FIELDS: dict[str, tuple[str, str | None]] = {
    "ZITADEL_URL": ("assetflow/idp", "url"),
    "ZITADEL_ISSUER": ("assetflow/idp", "issuer"),
    "ZITADEL_PROJECT_ID": ("assetflow/idp", "project_id"),
    "ZITADEL_WEB_CLIENT_ID": ("assetflow/idp", "web_client_id"),
    "ZITADEL_BFF_CLIENT_ID": ("assetflow/idp", "client_id"),
    "ZITADEL_BFF_CLIENT_SECRET": ("assetflow/idp", "client_secret"),
    "ZITADEL_INTROSPECTION_CLIENT_ID": ("assetflow/idp", "introspection_client_id"),
    "ZITADEL_INTROSPECTION_CLIENT_SECRET": ("assetflow/idp", "introspection_client_secret"),
    "ZITADEL_SERVICE_ACCOUNT_KEY": ("assetflow/zitadel/automation-key", "key_json"),
    "ZITADEL_BOOTSTRAP_KEY": ("assetflow/zitadel/bootstrap-key", "key_json"),
    "ZITADEL_ORGANIZATIONS": ("assetflow/zitadel/organizations", None),
}

# Local development secrets created by init-env (never used in production).
DEV_SECRETS = (
    "ZITADEL_MASTERKEY",
    "ZITADEL_ADMIN_PASSWORD",
    "ZITADEL_DB_PASSWORD",
    "ZITADEL_DB_USER_PASSWORD",
)
MASTERKEY_MARKER = ".masterkey.sha256"
ALNUM = string.ascii_letters + string.digits

JWT_BEARER = "urn:ietf:params:oauth:grant-type:jwt-bearer"
ZITADEL_API_SCOPE = "openid urn:zitadel:iam:org:project:id:zitadel:aud"


class BootstrapError(RuntimeError):
    """A step failed; the message says what to do."""


# ---------------------------------------------------------------- settings


def _bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    env: str = "development"
    root: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent)
    env_file: Path | None = None
    bootstrap_url: str = ""
    domain: str = "localhost"
    port: str = "8081"
    secure: bool = False
    app_url: str = "http://localhost:5173"
    api_url: str = "http://localhost:8080"
    key_file: Path = Path("/zitadel/bootstrap/bootstrap-key.json")
    pat_file: Path = Path("/zitadel/bootstrap/bootstrap.pat")
    admin_username: str = "admin"
    ready_timeout: float = 300.0
    dry_run: bool = False

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> Settings:
        e = dict(os.environ if environ is None else environ)
        s = cls()
        s.env = (e.get("ASSETFLOW_ENV") or "development").strip().lower()
        if e.get("ASSETFLOW_ROOT"):
            s.root = Path(e["ASSETFLOW_ROOT"])
        s.env_file = Path(e["ASSETFLOW_ENV_FILE"]) if e.get("ASSETFLOW_ENV_FILE") else s.root / ".env.local"
        s.domain = e.get("ZITADEL_DOMAIN") or e.get("ZITADEL_EXTERNALDOMAIN") or "localhost"
        s.port = e.get("ZITADEL_EXTERNALPORT") or "8081"
        s.secure = _bool(e.get("ZITADEL_EXTERNALSECURE"))
        s.bootstrap_url = (e.get("ZITADEL_BOOTSTRAP_URL") or f"http://localhost:{s.port}").rstrip("/")
        s.app_url = (e.get("APP_URL") or s.app_url).rstrip("/")
        s.api_url = (e.get("API_URL") or s.api_url).rstrip("/")
        if e.get("ZITADEL_FIRSTINSTANCE_KEY_FILE"):
            s.key_file = Path(e["ZITADEL_FIRSTINSTANCE_KEY_FILE"])
        if e.get("ZITADEL_FIRSTINSTANCE_PAT_FILE"):
            s.pat_file = Path(e["ZITADEL_FIRSTINSTANCE_PAT_FILE"])
        s.admin_username = e.get("ZITADEL_ADMIN_USERNAME") or "admin"
        if e.get("ZITADEL_READY_TIMEOUT"):
            s.ready_timeout = float(e["ZITADEL_READY_TIMEOUT"])
        return s

    @property
    def production(self) -> bool:
        return self.env == "production"

    @property
    def default_port(self) -> bool:
        return self.port == ("443" if self.secure else "80")

    @property
    def host_header(self) -> str:
        """Host Zitadel's instance is registered for (ExternalDomain[:ExternalPort])."""
        return self.domain if self.default_port else f"{self.domain}:{self.port}"

    @property
    def public_url(self) -> str:
        return f"{'https' if self.secure else 'http'}://{self.host_header}"


# ---------------------------------------------------------------- secret stores


def _one_line(name: str, value: str) -> None:
    if "\n" in value or "\r" in value:
        raise BootstrapError(f"{name} must be a single line")


class EnvFile:
    """A dotenv file: KEY=value lines; other lines and comments are kept as they are."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> dict[str, str]:
        values: dict[str, str] = {}
        if not self.path.exists():
            return values
        for raw in self.path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
        return values

    def update(self, values: dict[str, str]) -> list[str]:
        """Set keys in place (append new ones); returns the changed keys. Atomic replace."""
        current = self.read()
        changed = [k for k, v in values.items() if current.get(k) != v]
        if not changed:
            return []
        for key in changed:
            _one_line(key, values[key])
        lines = self.path.read_text(encoding="utf-8").splitlines() if self.path.exists() else []
        seen: set[str] = set()
        out: list[str] = []
        for raw in lines:
            key = raw.split("=", 1)[0].strip() if "=" in raw and not raw.lstrip().startswith("#") else None
            if key in values:
                out.append(f"{key}={values[key]}")
                seen.add(key)
            else:
                out.append(raw)
        new = [k for k in values if k not in seen and k in changed]
        if new:
            if out and out[-1].strip():
                out.append("")
            out.extend(f"{k}={values[k]}" for k in new)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
        with contextlib.suppress(OSError):
            tmp.chmod(0o600)
        os.replace(tmp, self.path)
        _match_owner(self.path)
        return changed


def _match_owner(path: Path) -> None:
    """In the bootstrap container (root) give the file to the owner of the checkout."""
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        return
    parent = path.parent.stat()
    with contextlib.suppress(OSError):
        os.chown(path, parent.st_uid, parent.st_gid)


class SecretStore:
    name = "store"

    def load(self) -> dict[str, str]:
        raise NotImplementedError

    def save(self, values: dict[str, str]) -> list[str]:
        raise NotImplementedError


class DevEnvStore(SecretStore):
    """Development only: results in .env.local (JSON keys base64-encoded)."""

    name = ".env.local"

    def __init__(self, path: Path, settings: Settings) -> None:
        if settings.production:
            raise BootstrapError("ASSETFLOW_ENV=production never writes secrets to files; use OpenBao")
        self.file = EnvFile(path)
        self.name = str(path)

    def load(self) -> dict[str, str]:
        raw = self.file.read()
        out: dict[str, str] = {}
        for key, value in raw.items():
            if key in KEY_FIELDS and value:
                try:
                    value = base64.b64decode(value).decode("utf-8")
                except ValueError:
                    continue
            out[key] = value
        return out

    def save(self, values: dict[str, str]) -> list[str]:
        encoded = {
            k: (base64.b64encode(v.encode("utf-8")).decode("ascii") if k in KEY_FIELDS else v)
            for k, v in values.items()
        }
        return self.file.update(encoded)


class OpenBaoStore(SecretStore):
    """Production: results in OpenBao KV v2, never in a file."""

    name = "OpenBao"

    def __init__(self, addr: str, token: str, cacert: str | None, client: httpx.Client | None = None) -> None:
        if not token:
            raise BootstrapError("set BAO_TOKEN (operator token); see docs/operations/openbao.md")
        verify: Any = cacert if cacert else True
        self.http = client or httpx.Client(base_url=addr.rstrip("/"), verify=verify, timeout=15)
        self.http.headers["X-Vault-Token"] = token
        self.name = f"OpenBao {addr}"

    def _get(self, path: str) -> dict[str, Any]:
        res = self.http.get(f"/v1/secret/data/{path}")
        if res.status_code == 404:
            return {}
        if res.status_code >= 400:
            raise BootstrapError(f"OpenBao read secret/{path}: HTTP {res.status_code}")
        return (res.json().get("data") or {}).get("data") or {}

    def load(self) -> dict[str, str]:
        cache: dict[str, dict[str, Any]] = {}
        out: dict[str, str] = {}
        for name, (path, key) in OPENBAO_FIELDS.items():
            data = cache.setdefault(path, self._get(path))
            if key is None:
                if data:
                    out[name] = ",".join(f"{k}:{v}" for k, v in sorted(data.items()))
            elif data.get(key):
                out[name] = str(data[key])
        return out

    def save(self, values: dict[str, str]) -> list[str]:
        by_path: dict[str, dict[str, Any]] = {}
        for name, value in values.items():
            path, key = OPENBAO_FIELDS[name]
            if key is None:
                by_path.setdefault(path, {}).update(_parse_org_map(value))
            else:
                by_path.setdefault(path, {})[key] = value
        changed: list[str] = []
        for path, wanted in by_path.items():
            current = self._get(path)
            merged = dict(current, **wanted)
            if merged == current:
                continue
            res = self.http.post(f"/v1/secret/data/{path}", json={"data": merged})
            if res.status_code >= 400:
                raise BootstrapError(f"OpenBao write secret/{path}: HTTP {res.status_code}")
            changed.extend(n for n in values if OPENBAO_FIELDS[n][0] == path)
        return changed


def _parse_org_map(value: str) -> dict[str, str]:
    pairs = (p.split(":", 1) for p in value.split(",") if ":" in p)
    return {k.strip(): v.strip() for k, v in pairs}


def make_store(settings: Settings, environ: dict[str, str] | None = None) -> SecretStore:
    e = dict(os.environ if environ is None else environ)
    if settings.production:
        return OpenBaoStore(
            e.get("BAO_ADDR", "https://127.0.0.1:8200"),
            e.get("BAO_TOKEN", "").strip(),
            e.get("BAO_CACERT") or None,
        )
    assert settings.env_file is not None
    return DevEnvStore(settings.env_file, settings)


# ---------------------------------------------------------------- Zitadel client


class ZitadelError(BootstrapError):
    def __init__(self, method: str, path: str, status: int, body: Any) -> None:
        self.status = status
        self.body = body
        message = body.get("message") if isinstance(body, dict) else body
        super().__init__(f"{method} {path}: HTTP {status} {message}")

    @property
    def already_exists(self) -> bool:
        return self.status == 409 or "already exist" in str(self).lower()

    @property
    def no_changes(self) -> bool:
        text = str(self).lower()
        return self.status in (400, 412) and ("no changes" in text or "not changed" in text)


class Zitadel:
    """Zitadel REST client. Sends the public Host header so an internal URL also works."""

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.settings = settings
        headers = {"Host": settings.host_header}
        if settings.secure:
            headers["X-Forwarded-Proto"] = "https"
        self.http = client or httpx.Client(base_url=settings.bootstrap_url, timeout=20)
        self.http.headers.update(headers)
        self.token: str | None = None

    def request(self, method: str, path: str, body: Any = None, org_id: str | None = None) -> Any:
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if org_id:
            headers["x-zitadel-orgid"] = org_id
        res = self.http.request(method, path, json=body, headers=headers)
        try:
            payload = res.json() if res.content else {}
        except ValueError:
            payload = res.text
        if res.status_code >= 400:
            raise ZitadelError(method, path, res.status_code, payload)
        return payload

    def post(self, path: str, body: Any = None, org_id: str | None = None) -> Any:
        return self.request("POST", path, {} if body is None else body, org_id)

    def put(self, path: str, body: Any, org_id: str | None = None) -> Any:
        return self.request("PUT", path, body, org_id)

    def get(self, path: str, org_id: str | None = None) -> Any:
        return self.request("GET", path, None, org_id)

    def delete(self, path: str, org_id: str | None = None) -> Any:
        return self.request("DELETE", path, None, org_id)

    # -- readiness and auth -------------------------------------------------------
    def wait_ready(self, timeout: float, sleep: Callable[[float], None] = time.sleep) -> None:
        deadline = time.monotonic() + timeout
        last = ""
        while True:
            try:
                res = self.http.get("/debug/ready")
                if res.status_code == 200:
                    return
                last = f"HTTP {res.status_code}"
            except httpx.HTTPError as exc:
                last = str(exc)
            if time.monotonic() >= deadline:
                raise BootstrapError(
                    f"Zitadel at {self.settings.bootstrap_url} not ready after {timeout}s: {last}"
                )
            sleep(2)

    def issuer(self) -> str:
        return self.get("/.well-known/openid-configuration")["issuer"]

    def token_from_key(self, key_json: str) -> str:
        key = json.loads(key_json)
        now = int(time.time())
        assertion = jwt.encode(
            {"iss": key["userId"], "sub": key["userId"], "aud": self.issuer(), "iat": now, "exp": now + 300},
            key["key"],
            algorithm="RS256",
            headers={"kid": key["keyId"]},
        )
        res = self.http.post(
            "/oauth/v2/token",
            data={"grant_type": JWT_BEARER, "scope": ZITADEL_API_SCOPE, "assertion": assertion},
        )
        if res.status_code != 200:
            raise BootstrapError(f"JWT profile grant failed: HTTP {res.status_code} {res.text[:200]}")
        return res.json()["access_token"]

    def introspection_ok(self, client_id: str, client_secret: str) -> bool:
        """True when Zitadel accepts these credentials at the introspection endpoint."""
        res = self.http.post("/oauth/v2/introspect", data={"token": "probe"}, auth=(client_id, client_secret))
        return res.status_code == 200


# ---------------------------------------------------------------- config


@dataclass
class OrgSpec:
    slug: str
    name: str
    roles: list[str]


def load_roles(root: Path) -> dict[str, str]:
    """rbac.roles from config/assetflow.yaml (list of keys, or key -> {display_name}), else defaults."""
    path = root / "config" / "assetflow.yaml"
    if not path.exists():
        return dict(DEFAULT_ROLES)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    roles = (data.get("rbac") or {}).get("roles")
    if not roles:
        return dict(DEFAULT_ROLES)
    if isinstance(roles, list):
        return {str(r): DEFAULT_ROLES.get(str(r), str(r).replace("_", " ").capitalize()) for r in roles}
    return {
        str(k): str((v or {}).get("display_name") or DEFAULT_ROLES.get(str(k), k))
        if isinstance(v, dict)
        else str(v)
        for k, v in roles.items()
    }


def load_organizations(root: Path, roles: dict[str, str]) -> list[OrgSpec]:
    orgs: list[OrgSpec] = []
    for path in sorted((root / "config" / "organizations").glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        slug = data.get("slug")
        if slug != path.stem:
            raise BootstrapError(f"{path.name}: slug must equal the file name ({path.stem})")
        if not data.get("name"):
            raise BootstrapError(f"{path.name}: name is required")
        granted = list((data.get("idp") or {}).get("granted_roles") or [])
        unknown = sorted(set(granted) - set(roles))
        if not granted or unknown:
            raise BootstrapError(
                f"{path.name}: idp.granted_roles must list AssetFlow project roles only"
                + (f" (unknown: {', '.join(unknown)})" if unknown else "")
            )
        orgs.append(OrgSpec(slug=slug, name=str(data["name"]), roles=granted))
    return orgs


# ---------------------------------------------------------------- bootstrap


def _eq(name: str) -> dict[str, str]:
    return {"name": name, "method": "TEXT_QUERY_METHOD_EQUALS"}


class Bootstrap:
    def __init__(
        self, settings: Settings, zitadel: Zitadel, store: SecretStore, out: Callable[[str], None] = print
    ):
        self.s = settings
        self.z = zitadel
        self.store = store
        self.out = out
        self.actions: list[str] = []
        self.stored: dict[str, str] = {}
        self.results: dict[str, str] = {}
        self.platform_org = ""

    # -- reporting ----------------------------------------------------------------
    def act(self, verb: str, what: str) -> None:
        """Record a change: verb is "created" or "changed" ("would create/update" in a dry run)."""
        prefix = {"created": "would create", "changed": "would update"}[verb] if self.s.dry_run else verb
        self.actions.append(f"{verb} {what}")
        self.out(f"  {prefix}: {what}")

    def ok(self, what: str) -> None:
        self.out(f"  ok: {what}")

    def keep(self, name: str, value: str) -> None:
        self.results[name] = value

    def persist(self, values: dict[str, str]) -> None:
        """Store values at once (before anything that would lose them)."""
        self.results.update(values)
        if self.s.dry_run:
            return
        for name in self.store.save(values):
            label = "(value not shown)" if name in SECRET_FIELDS else f"= {values.get(name, '')}"
            self.out(f"  stored {name} in {self.store.name} {label}")

    # -- steps --------------------------------------------------------------------
    def run(self) -> dict[str, str]:
        roles = load_roles(self.s.root)
        orgs = load_organizations(self.s.root, roles)
        mode = "production (OpenBao)" if self.s.production else "development (.env.local)"
        self.out(f"==> Zitadel bootstrap: {self.s.public_url} via {self.s.bootstrap_url}, {mode}")
        if self.s.dry_run:
            self.out("    dry run: nothing is changed")
        self.z.wait_ready(self.s.ready_timeout)
        self.ok("Zitadel is ready")
        self.stored = self.store.load()
        self.authenticate()
        self.platform_org = self.z.get("/management/v1/orgs/me")["org"]["id"]
        project_id = self.project()
        self.roles(project_id, roles)
        self.web_app(project_id)
        self.bff_app(project_id)
        self.introspection_app(project_id)
        self.automation_user()
        org_ids = self.organizations(project_id, orgs)
        if self.s.production:
            self.login_policy()
        self.persist(
            {
                "ZITADEL_URL": self.s.public_url,
                "ZITADEL_ISSUER": self.z.issuer(),
                "ZITADEL_PROJECT_ID": project_id or "",
                "ZITADEL_ORGANIZATIONS": ",".join(f"{k}:{v}" for k, v in sorted(org_ids.items())),
                **{k: v for k, v in self.results.items() if k not in SECRET_FIELDS},
            }
        )
        self.summary(project_id, org_ids)
        return self.results

    def authenticate(self) -> None:
        stored_key = self.stored.get("ZITADEL_BOOTSTRAP_KEY")
        if stored_key:
            try:
                self.z.token = self.z.token_from_key(stored_key)
                self.ok("authenticated with the stored bootstrap key (JWT profile grant)")
                return
            except (BootstrapError, ValueError, KeyError) as exc:
                self.out(f"  warning: stored bootstrap key rejected ({exc}); trying the first-instance key")
        if self.s.key_file.exists():
            key_json = self.s.key_file.read_text(encoding="utf-8").strip()
            self.z.token = self.z.token_from_key(key_json)
            self.ok(f"authenticated with the first-instance machine key {self.s.key_file}")
            self.rotate_first_key(json.loads(key_json))
            return
        if self.s.pat_file.exists():
            self.z.token = self.s.pat_file.read_text(encoding="utf-8").strip()
            user_id = self.z.get("/auth/v1/users/me")["user"]["id"]
            self.ok(f"authenticated with the first-instance PAT {self.s.pat_file}")
            self.rotate_first_key({"userId": user_id}, pat=True)
            return
        where = (
            "OpenBao secret/assetflow/zitadel/bootstrap-key" if self.s.production else "ZITADEL_BOOTSTRAP_KEY"
        )
        raise BootstrapError(
            f"no Zitadel credential: {where} is missing or invalid and no first-instance key or PAT is at "
            f"{self.s.key_file} / {self.s.pat_file}. See docs/operations/zitadel.md (recovery)."
        )

    def rotate_first_key(self, old: dict[str, Any], pat: bool = False) -> None:
        """Replace the credential Zitadel wrote to the volume: store a new key, revoke the old one."""
        user_id = old["userId"]
        what = "first-instance PAT" if pat else f"first-instance key {old.get('keyId')}"
        if self.s.dry_run:
            self.act("changed", f"rotate the {what} into the secret store and delete the file")
            return
        created = self.z.post(
            f"/management/v1/users/{user_id}/keys",
            {"type": "KEY_TYPE_JSON", "expirationDate": KEY_EXPIRATION},
        )
        new_key = base64.b64decode(created["keyDetails"]).decode("utf-8")
        self.persist({"ZITADEL_BOOTSTRAP_KEY": new_key})
        self.z.token = self.z.token_from_key(new_key)
        if pat:
            for p in self.z.post(f"/management/v1/users/{user_id}/pats/_search").get("result", []):
                self.z.delete(f"/management/v1/users/{user_id}/pats/{p['id']}")
            self.s.pat_file.unlink(missing_ok=True)
        else:
            self.z.delete(f"/management/v1/users/{user_id}/keys/{old['keyId']}")
            self.s.key_file.unlink(missing_ok=True)
        self.act("changed", f"rotated the {what}: new key stored, old credential revoked and file deleted")

    def project(self) -> str:
        body = {
            "name": PROJECT_NAME,
            # Roles are asserted in the tokens (checked locally against JWKS).
            "projectRoleAssertion": True,
            # Only users with a role of this project, and of an organization with a grant, sign in.
            "projectRoleCheck": True,
            "hasProjectCheck": True,
            "privateLabelingSetting": "PRIVATE_LABELING_SETTING_ENFORCE_PROJECT_RESOURCE_OWNER_POLICY",
        }
        found = self.z.post(
            "/management/v1/projects/_search", {"queries": [{"nameQuery": _eq(PROJECT_NAME)}]}
        )
        existing = next((p for p in found.get("result", []) if p.get("name") == PROJECT_NAME), None)
        if existing is None:
            if self.s.dry_run:
                self.act("created", f"project {PROJECT_NAME}")
                return ""
            project_id = self.z.post("/management/v1/projects", body)["id"]
            self.act("created", f"project {PROJECT_NAME} ({project_id})")
            return project_id
        project_id = existing["id"]
        current = self.z.get(f"/management/v1/projects/{project_id}").get("project", {})
        self.update(
            f"/management/v1/projects/{project_id}", body, f"project {PROJECT_NAME} ({project_id})", current
        )
        return project_id

    def update(
        self, path: str, body: dict[str, Any], what: str, current: dict[str, Any] | None = None
    ) -> None:
        """Re-apply settings with PUT unless ``current`` already matches; Zitadel's 'No changes' is success."""
        if current is not None and all(current.get(k) == v for k, v in body.items()):
            self.ok(f"{what} up to date")
            return
        if self.s.dry_run:
            self.ok(f"{what} exists (settings re-applied on a real run)")
            return
        try:
            self.z.put(path, body)
        except ZitadelError as exc:
            if exc.no_changes:
                self.ok(f"{what} up to date")
                return
            raise
        self.act("changed", f"{what} settings")

    def roles(self, project_id: str, roles: dict[str, str]) -> None:
        before = len(self.actions)
        existing: dict[str, dict[str, Any]] = {}
        if project_id:
            found = self.z.post(
                f"/management/v1/projects/{project_id}/roles/_search", {"query": {"limit": 1000}}
            )
            existing = {r["key"]: r for r in found.get("result", [])}
        for key, display in roles.items():
            current = existing.get(key)
            if current is None:
                if not self.s.dry_run:
                    try:
                        self.z.post(
                            f"/management/v1/projects/{project_id}/roles",
                            {"roleKey": key, "displayName": display, "group": ROLE_GROUP},
                        )
                    except ZitadelError as exc:
                        if not exc.already_exists:
                            raise
                        self.ok(f"role {key} exists")
                        continue
                self.act("created", f"role {key}")
            elif current.get("displayName") != display or current.get("group") != ROLE_GROUP:
                if not self.s.dry_run:
                    self.z.put(
                        f"/management/v1/projects/{project_id}/roles/{key}",
                        {"displayName": display, "group": ROLE_GROUP},
                    )
                self.act("changed", f"role {key}")
        extra = sorted(set(existing) - set(roles))
        if extra:
            self.out(f"  note: roles in Zitadel but not in config (kept): {', '.join(extra)}")
        if len(self.actions) == before:
            self.ok(f"{len(roles)} project roles up to date")

    def find_app(self, project_id: str, name: str) -> dict[str, Any] | None:
        if not project_id:
            return None
        found = self.z.post(
            f"/management/v1/projects/{project_id}/apps/_search", {"queries": [{"nameQuery": _eq(name)}]}
        )
        return next((a for a in found.get("result", []) if a.get("name") == name), None)

    def _oidc(self, app_type: str, auth: str, redirects: list[str], logouts: list[str]) -> dict[str, Any]:
        return {
            "redirectUris": redirects,
            "postLogoutRedirectUris": logouts,
            "responseTypes": ["OIDC_RESPONSE_TYPE_CODE"],
            "grantTypes": ["OIDC_GRANT_TYPE_AUTHORIZATION_CODE", "OIDC_GRANT_TYPE_REFRESH_TOKEN"],
            "appType": app_type,
            "authMethodType": auth,
            # http:// redirect URIs are allowed only outside production.
            "devMode": not self.s.production,
            "accessTokenType": "OIDC_TOKEN_TYPE_JWT",
            "accessTokenRoleAssertion": True,
            "idTokenRoleAssertion": True,
            "idTokenUserinfoAssertion": True,
            "clockSkew": "0s",
        }

    def _app(self, project_id: str, name: str, config: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Create or re-apply one OIDC app. Returns (app or create response, created)."""
        app = self.find_app(project_id, name)
        if app is None:
            if self.s.dry_run:
                self.act("created", f"OIDC app {name}")
                return {}, True
            created = self.z.post(f"/management/v1/projects/{project_id}/apps/oidc", {"name": name, **config})
            self.act("created", f"OIDC app {name} (client id {created['clientId']})")
            return created, True
        self.update(
            f"/management/v1/projects/{project_id}/apps/{app['id']}/oidc_config", config, f"OIDC app {name}"
        )
        return app, False

    def web_app(self, project_id: str) -> None:
        config = self._oidc(
            "OIDC_APP_TYPE_USER_AGENT",
            "OIDC_AUTH_METHOD_TYPE_NONE",  # public client: PKCE, no secret
            [f"{self.s.app_url}/auth/callback"],
            [f"{self.s.app_url}/"],
        )
        app, created = self._app(project_id, WEB_APP, config)
        client_id = app.get("clientId") if created else (app.get("oidcConfig") or {}).get("clientId")
        self.keep("ZITADEL_WEB_CLIENT_ID", client_id or "")

    def bff_app(self, project_id: str) -> None:
        config = self._oidc(
            "OIDC_APP_TYPE_WEB",
            "OIDC_AUTH_METHOD_TYPE_BASIC",
            [f"{self.s.api_url}/api/v1/auth/callback"],
            [f"{self.s.api_url}/"],
        )
        app, created = self._app(project_id, BFF_APP, config)
        if self.s.dry_run:
            self.keep("ZITADEL_BFF_CLIENT_ID", (app.get("oidcConfig") or {}).get("clientId", ""))
            return
        if created:
            client_id, secret = app["clientId"], app.get("clientSecret", "")
        else:
            client_id = (app.get("oidcConfig") or {}).get("clientId", "")
            secret = self.stored.get("ZITADEL_BFF_CLIENT_SECRET", "")
            if not secret or self.stored.get("ZITADEL_BFF_CLIENT_ID") != client_id:
                secret = self.z.post(
                    f"/management/v1/projects/{project_id}/apps/{app['id']}/oidc_config/_generate_client_secret"
                )["clientSecret"]
                self.act("changed", f"new client secret for {BFF_APP} (none stored)")
        self.persist({"ZITADEL_BFF_CLIENT_ID": client_id, "ZITADEL_BFF_CLIENT_SECRET": secret})

    def machine_user(self, username: str, name: str, description: str) -> tuple[str, bool]:
        found = self.z.post(
            "/management/v1/users/_search",
            {"queries": [{"userNameQuery": {"userName": username, "method": "TEXT_QUERY_METHOD_EQUALS"}}]},
        )
        user = next((u for u in found.get("result", []) if u.get("userName") == username), None)
        if user:
            self.ok(f"machine user {username} exists")
            return user["id"], False
        if self.s.dry_run:
            self.act("created", f"machine user {username}")
            return "", True
        try:
            user_id = self.z.post(
                "/management/v1/users/machine",
                {
                    "userName": username,
                    "name": name,
                    "description": description,
                    "accessTokenType": "ACCESS_TOKEN_TYPE_JWT",
                },
            )["userId"]
        except ZitadelError as exc:
            if exc.already_exists:
                raise BootstrapError(
                    f"machine user {username} exists but was not found by search; retry"
                ) from exc
            raise
        self.act("created", f"machine user {username} ({user_id})")
        return user_id, True

    def introspection_app(self, project_id: str) -> None:
        """API application with client secret (basic auth) for /oauth/v2/introspect.

        Zitadel's introspection endpoint authenticates API or OIDC applications of the project;
        a machine user's client secret is refused there (unauthorized_client).
        """
        config = {"authMethodType": "API_AUTH_METHOD_TYPE_BASIC"}
        app = self.find_app(project_id, INTROSPECTION_APP)
        if app is None:
            if self.s.dry_run:
                self.act("created", f"API app {INTROSPECTION_APP}")
                return
            created = self.z.post(
                f"/management/v1/projects/{project_id}/apps/api", {"name": INTROSPECTION_APP, **config}
            )
            client_id, secret = created["clientId"], created["clientSecret"]
            self.act("created", f"API app {INTROSPECTION_APP} (client id {client_id})")
        else:
            api = app.get("apiConfig") or {}
            # BASIC is the enum default and is left out of the JSON response.
            current = {"authMethodType": api.get("authMethodType", "API_AUTH_METHOD_TYPE_BASIC")}
            path = f"/management/v1/projects/{project_id}/apps/{app['id']}/api_config"
            self.update(path, config, f"API app {INTROSPECTION_APP}", current)
            if self.s.dry_run:
                return
            client_id = api.get("clientId", "")
            secret = self.stored.get("ZITADEL_INTROSPECTION_CLIENT_SECRET", "")
            if (
                not secret
                or self.stored.get("ZITADEL_INTROSPECTION_CLIENT_ID") != client_id
                or not self.z.introspection_ok(client_id, secret)
            ):
                secret = self.z.post(f"{path}/_generate_client_secret")["clientSecret"]
                self.act("changed", f"new client secret for {INTROSPECTION_APP} (none valid stored)")
        self.persist(
            {"ZITADEL_INTROSPECTION_CLIENT_ID": client_id, "ZITADEL_INTROSPECTION_CLIENT_SECRET": secret}
        )

    def automation_user(self) -> None:
        user_id, created = self.machine_user(
            AUTOMATION_USER,
            "AssetFlow organization automation",
            "Creates Zitadel organizations and project grants for AssetFlow organizations",
        )
        if self.s.dry_run:
            if created:
                self.act("created", f"instance member {AUTOMATION_USER} {AUTOMATION_ROLES} and JSON key")
            return
        members = self.z.post(
            "/admin/v1/members/_search", {"queries": [{"userIdQuery": {"userId": user_id}}]}
        )
        member = next((m for m in members.get("result", []) if m.get("userId") == user_id), None)
        if member is None:
            try:
                self.z.post("/admin/v1/members", {"userId": user_id, "roles": AUTOMATION_ROLES})
                self.act("created", f"instance member {AUTOMATION_USER} {AUTOMATION_ROLES}")
            except ZitadelError as exc:
                if not exc.already_exists:
                    raise
        elif sorted(member.get("roles", [])) != sorted(AUTOMATION_ROLES):
            self.z.put(f"/admin/v1/members/{user_id}", {"roles": AUTOMATION_ROLES})
            self.act("changed", f"instance member roles of {AUTOMATION_USER}")
        stored = self.stored.get("ZITADEL_SERVICE_ACCOUNT_KEY", "")
        stored_id = ""
        with contextlib.suppress(ValueError, KeyError):
            stored_id = json.loads(stored)["keyId"] if stored else ""
        keys = {
            k["id"] for k in self.z.post(f"/management/v1/users/{user_id}/keys/_search").get("result", [])
        }
        if created or not stored_id or stored_id not in keys:
            res = self.z.post(
                f"/management/v1/users/{user_id}/keys",
                {"type": "KEY_TYPE_JSON", "expirationDate": KEY_EXPIRATION},
            )
            stored = base64.b64decode(res["keyDetails"]).decode("utf-8")
            self.act("created", f"JSON key {res['keyId']} for {AUTOMATION_USER}")
        self.persist({"ZITADEL_SERVICE_ACCOUNT_KEY": stored})

    def organizations(self, project_id: str, orgs: list[OrgSpec]) -> dict[str, str]:
        grants: dict[str, dict[str, Any]] = {}
        if project_id:
            found = self.z.post(
                f"/management/v1/projects/{project_id}/grants/_search", {"query": {"limit": 1000}}
            )
            grants = {g["grantedOrgId"]: g for g in found.get("result", [])}
        ids: dict[str, str] = {}
        for spec in orgs:
            org_id = self.org(spec)
            if org_id:
                ids[spec.slug] = org_id
            grant = grants.get(org_id) if org_id else None
            what = f"project grant {PROJECT_NAME} -> {spec.slug} [{', '.join(spec.roles)}]"
            if grant is None:
                if not self.s.dry_run:
                    try:
                        self.z.post(
                            f"/management/v1/projects/{project_id}/grants",
                            {"grantedOrgId": org_id, "roleKeys": spec.roles},
                        )
                    except ZitadelError as exc:
                        if not exc.already_exists:
                            raise
                        self.ok(f"{what} exists")
                        continue
                self.act("created", what)
            elif sorted(grant.get("grantedRoleKeys", [])) != sorted(spec.roles):
                if not self.s.dry_run:
                    self.z.put(
                        f"/management/v1/projects/{project_id}/grants/{grant['grantId']}",
                        {"roleKeys": spec.roles},
                    )
                self.act("changed", what)
            else:
                self.ok(what)
        return ids

    def org(self, spec: OrgSpec) -> str:
        def search() -> str:
            found = self.z.post("/admin/v1/orgs/_search", {"queries": [{"nameQuery": _eq(spec.name)}]})
            return next((o["id"] for o in found.get("result", []) if o.get("name") == spec.name), "")

        org_id = search()
        if org_id:
            self.ok(f"organization {spec.slug} ({spec.name}) = {org_id}")
            return org_id
        if self.s.dry_run:
            self.act("created", f"organization {spec.slug} ({spec.name})")
            return ""
        try:
            org_id = self.z.post("/v2/organizations", {"name": spec.name})["organizationId"]
        except ZitadelError as exc:
            if not exc.already_exists:
                raise
            org_id = search()
        self.act("created", f"organization {spec.slug} ({spec.name}) = {org_id}")
        return org_id

    def login_policy(self) -> None:
        """Production: MFA forced and self-registration off on the instance login policy."""
        policy = self.z.get("/admin/v1/policies/login").get("policy", {})
        if policy.get("forceMfa") is True and not policy.get("allowRegister"):
            self.ok("login policy: MFA forced, self-registration off")
            return
        body = {
            k: v
            for k, v in policy.items()
            if k not in {"details", "isDefault", "secondFactors", "multiFactors", "idps"}
        }
        body.update({"forceMfa": True, "allowRegister": False})
        if not self.s.dry_run:
            self.z.put("/admin/v1/policies/login", body)
        self.act("changed", "login policy: force MFA, disable self-registration")

    def summary(self, project_id: str, org_ids: dict[str, str]) -> None:
        admin = ""
        with contextlib.suppress(BootstrapError, KeyError):
            found = self.z.post(
                "/management/v1/users/_search",
                {
                    "queries": [
                        {
                            "userNameQuery": {
                                "userName": self.s.admin_username,
                                "method": "TEXT_QUERY_METHOD_STARTS_WITH",
                            }
                        }
                    ]
                },
            )
            # The login name gets the organization domain as suffix (UserLoginMustBeDomain=false).
            name = self.s.admin_username
            users = [
                u
                for u in found.get("result", [])
                if "human" in u and u.get("userName", "").split("@")[0] == name
            ]
            admin = users[0].get("preferredLoginName", "") if users else ""
        self.out(
            f"==> console:     {self.s.public_url}/ui/console"
            + (f"  (admin login: {admin})" if admin else "")
        )
        self.out(f"==> project_id:  {project_id or '(not created yet)'}  (token audience)")
        self.out(f"==> web client:  {self.results.get('ZITADEL_WEB_CLIENT_ID', '')}")
        self.out(f"==> bff client:  {self.results.get('ZITADEL_BFF_CLIENT_ID', '')}")
        for slug, org_id in sorted(org_ids.items()):
            self.out(f"==> organization {slug}: idp_organization_id {org_id}")
        if self.s.dry_run:
            self.out(f"==> Dry run: {len(self.actions)} planned change(s).")
        elif self.actions:
            self.out(f"==> Applied {len(self.actions)} change(s).")
        else:
            self.out("==> No changes.")


# ---------------------------------------------------------------- init-env (development)


def _random(length: int) -> str:
    return "".join(secrets.choice(ALNUM) for _ in range(length))


def admin_password() -> str:
    """32 characters meeting Zitadel's default complexity; no $ or % (compose interpolation)."""
    while True:
        core = _random(30)
        if (
            any(c.isupper() for c in core)
            and any(c.islower() for c in core)
            and any(c.isdigit() for c in core)
        ):
            return core + "@!"


def init_env(settings: Settings, marker_dir: Path | None, out: Callable[[str], None] = print) -> int:
    if settings.production:
        raise BootstrapError("init-env is for local development only; production secrets live in OpenBao")
    assert settings.env_file is not None
    env = EnvFile(settings.env_file)
    current = env.read()
    generators = {
        "ZITADEL_MASTERKEY": lambda: _random(32),
        "ZITADEL_ADMIN_PASSWORD": admin_password,
        "ZITADEL_DB_PASSWORD": lambda: _random(32),
        "ZITADEL_DB_USER_PASSWORD": lambda: _random(32),
    }
    values = {k: current.get(k) or generators[k]() for k in DEV_SECRETS}
    if len(values["ZITADEL_MASTERKEY"]) != 32:
        raise BootstrapError("ZITADEL_MASTERKEY in .env.local must be exactly 32 characters")
    fingerprint = hashlib.sha256(values["ZITADEL_MASTERKEY"].encode()).hexdigest()
    marker = marker_dir / MASTERKEY_MARKER if marker_dir else None
    if marker and marker.exists() and marker.read_text(encoding="utf-8").strip() != fingerprint:
        raise BootstrapError(
            "the Zitadel volumes were created with a different masterkey than ZITADEL_MASTERKEY in "
            f"{settings.env_file} (for example .env.local was deleted or regenerated). Zitadel cannot decrypt "
            "its data with another key. Either restore the original .env.local, or delete the local "
            "identity volumes and start again: scripts/bootstrap.sh --reset (Windows: setup.bat -Reset)."
        )
    created = env.update(values)
    for key in created:
        out(f"  generated {key} in {settings.env_file} (value not shown)")
    if marker and not marker.exists():
        marker.write_text(fingerprint + "\n", encoding="utf-8")
    if not created:
        out(f"  ok: local secrets present in {settings.env_file}")
    return 0


# ---------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", nargs="?", default="apply", choices=["apply", "init-env"])
    parser.add_argument("--dry-run", action="store_true", help="print planned actions, change nothing")
    parser.add_argument(
        "--marker-dir", type=Path, help="init-env: bootstrap volume that records the masterkey hash"
    )
    args = parser.parse_args(argv)
    with contextlib.suppress(AttributeError):
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]
    settings = Settings.from_env()
    settings.dry_run = args.dry_run
    try:
        if args.command == "init-env":
            return init_env(settings, args.marker_dir)
        Bootstrap(settings, Zitadel(settings), make_store(settings)).run()
    except (BootstrapError, httpx.HTTPError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
