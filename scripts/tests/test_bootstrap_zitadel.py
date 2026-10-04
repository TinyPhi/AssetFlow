# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for scripts/bootstrap_zitadel.py against an in-memory Zitadel (httpx.MockTransport).

Run: make test-scripts
"""

from __future__ import annotations

import base64
import itertools
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

SCRIPTS = Path(__file__).resolve().parent.parent
REPO = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

import bootstrap_zitadel as bz

ISSUER = "http://localhost:19081"
PEM = (
    rsa.generate_private_key(public_exponent=65537, key_size=2048)
    .private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    .decode()
)
SEARCH_OR_AUTH = re.compile(r"(_search|/oauth/v2/|/debug/|well-known)")


def _key_json(user_id: str, key_id: str) -> str:
    return json.dumps({"type": "serviceaccount", "keyId": key_id, "key": PEM, "userId": user_id})


class FakeZitadel:
    """Just enough of Zitadel's Management/Admin/v2 REST APIs, with state."""

    def __init__(self, conflict_on_role_create: bool = False) -> None:
        self.seq = itertools.count(1000)
        self.conflict_on_role_create = conflict_on_role_create
        self.projects: dict[str, dict[str, Any]] = {}
        self.roles: dict[tuple[str, str], dict[str, Any]] = {}
        self.apps: dict[str, dict[str, Any]] = {}
        self.users: dict[str, dict[str, Any]] = {
            "boot": {"id": "boot", "userName": "assetflow-bootstrap", "keys": {"k0"}, "machine": {}},
            "human": {
                "id": "human",
                "userName": "admin@assetflow-platform.localhost",
                "preferredLoginName": "admin@assetflow-platform.localhost",
                "human": {},
                "keys": set(),
            },
        }
        self.members: dict[str, list[str]] = {"boot": ["IAM_OWNER"]}
        self.orgs: dict[str, str] = {"platform": "AssetFlow Platform"}
        self.grants: dict[str, dict[str, Any]] = {}
        self.policy: dict[str, Any] = {
            "forceMfa": False,
            "allowRegister": True,
            "allowUsernamePassword": True,
        }
        self.calls: list[tuple[str, str]] = []
        self.statuses: list[int] = []
        self.hosts: set[str] = set()

    def new_id(self) -> str:
        return str(next(self.seq))

    @property
    def mutations(self) -> list[tuple[str, str]]:
        """Calls that changed state (a PUT answered with "No changes" did not)."""
        return [
            (m, p)
            for (m, p), status in zip(self.calls, self.statuses, strict=True)
            if m != "GET" and not SEARCH_OR_AUTH.search(p) and status < 300
        ]

    # -- dispatcher -----------------------------------------------------------------
    def __call__(self, request: httpx.Request) -> httpx.Response:
        response = self.dispatch(request)
        self.calls.append((request.method, request.url.path))
        self.statuses.append(response.status_code)
        return response

    def dispatch(self, request: httpx.Request) -> httpx.Response:
        method, path = request.method, request.url.path
        self.hosts.add(request.headers.get("host", ""))
        body: Any = {}
        if request.content and request.headers.get("content-type", "").startswith("application/json"):
            body = json.loads(request.content)
        if not path.startswith(
            ("/debug", "/.well-known", "/oauth")
        ) and "Bearer tok-" not in request.headers.get("authorization", ""):
            return httpx.Response(401, json={"message": "no token"})
        for pattern, handler in self.routes():
            m = re.fullmatch(pattern, f"{method} {path}")
            if m:
                return handler(request, body, *m.groups())
        return httpx.Response(404, json={"message": f"no route {method} {path}"})

    def routes(self) -> list[tuple[str, Any]]:
        p = r"/management/v1/projects/(\w+)"
        return [
            (r"GET /debug/ready", lambda *_: httpx.Response(200, text="ok")),
            (
                r"GET /\.well-known/openid-configuration",
                lambda *_: httpx.Response(200, json={"issuer": ISSUER}),
            ),
            (r"POST /oauth/v2/token", self.token),
            (r"POST /oauth/v2/introspect", self.introspect),
            (r"GET /management/v1/orgs/me", lambda *_: httpx.Response(200, json={"org": {"id": "platform"}})),
            (r"POST /management/v1/projects/_search", self.project_search),
            (r"POST /management/v1/projects", self.project_create),
            (rf"GET {p}", lambda _r, _b, pid: httpx.Response(200, json={"project": self.projects[pid]})),
            (rf"PUT {p}", self.project_update),
            (rf"POST {p}/roles/_search", self.role_search),
            (rf"POST {p}/roles", self.role_create),
            (rf"PUT {p}/roles/(\w+)", self.role_update),
            (rf"POST {p}/apps/_search", self.app_search),
            (rf"POST {p}/apps/oidc", self.oidc_create),
            (rf"POST {p}/apps/api", self.api_create),
            (rf"PUT {p}/apps/(\w+)/(oidc_config|api_config)", self.app_update),
            (rf"POST {p}/apps/(\w+)/(?:oidc_config|api_config)/_generate_client_secret", self.app_secret),
            (rf"POST {p}/grants/_search", self.grant_search),
            (rf"POST {p}/grants", self.grant_create),
            (rf"PUT {p}/grants/(\w+)", self.grant_update),
            (r"POST /management/v1/users/_search", self.user_search),
            (r"POST /management/v1/users/machine", self.user_create),
            (r"POST /management/v1/users/(\w+)/keys/_search", self.key_search),
            (r"POST /management/v1/users/(\w+)/keys", self.key_create),
            (r"DELETE /management/v1/users/(\w+)/keys/(\w+)", self.key_delete),
            (r"POST /admin/v1/members/_search", self.member_search),
            (r"POST /admin/v1/members", self.member_create),
            (r"POST /admin/v1/orgs/_search", self.org_search),
            (r"POST /v2/organizations", self.org_create),
            (
                r"GET /admin/v1/policies/login",
                lambda *_: httpx.Response(200, json={"policy": dict(self.policy)}),
            ),
            (r"PUT /admin/v1/policies/login", self.policy_update),
        ]

    # -- auth -------------------------------------------------------------------------
    def token(self, request: httpx.Request, _body: Any) -> httpx.Response:
        form = dict(httpx.QueryParams(request.content.decode()))
        claims = jwt.decode(form["assertion"], options={"verify_signature": False})
        kid = jwt.get_unverified_header(form["assertion"])["kid"]
        user = self.users.get(claims["sub"])
        if claims["aud"] != ISSUER or user is None or kid not in user["keys"]:
            return httpx.Response(400, json={"error": "invalid_grant"})
        return httpx.Response(200, json={"access_token": f"tok-{claims['sub']}"})

    def introspect(self, request: httpx.Request, _body: Any) -> httpx.Response:
        user, _, secret = (
            base64.b64decode(request.headers["authorization"].split()[1]).decode().partition(":")
        )
        ok = any(a.get("clientId") == user and a.get("secret") == secret for a in self.apps.values())
        return httpx.Response(
            200 if ok else 401, json={"active": False} if ok else {"error": "invalid_client"}
        )

    # -- projects and roles -------------------------------------------------------------
    def project_search(self, _r: Any, body: Any) -> httpx.Response:
        name = body["queries"][0]["nameQuery"]["name"]
        return httpx.Response(200, json={"result": [p for p in self.projects.values() if p["name"] == name]})

    def project_create(self, _r: Any, body: Any) -> httpx.Response:
        pid = self.new_id()
        self.projects[pid] = {"id": pid, **body}
        return httpx.Response(200, json={"id": pid})

    def project_update(self, _r: Any, body: Any, pid: str) -> httpx.Response:
        self.projects[pid].update(body)
        return httpx.Response(200, json={"details": {}})  # like Zitadel: 200 even without a change

    def role_search(self, _r: Any, _b: Any, pid: str) -> httpx.Response:
        return httpx.Response(200, json={"result": [r for (p, _), r in self.roles.items() if p == pid]})

    def role_create(self, _r: Any, body: Any, pid: str) -> httpx.Response:
        if self.conflict_on_role_create or (pid, body["roleKey"]) in self.roles:
            self.roles[(pid, body["roleKey"])] = {"key": body["roleKey"], "displayName": body["displayName"]}
            return httpx.Response(409, json={"code": 6, "message": "Role already exists (COMMAND-8ie7s)"})
        self.roles[(pid, body["roleKey"])] = {
            "key": body["roleKey"],
            "displayName": body["displayName"],
            "group": body["group"],
        }
        return httpx.Response(200, json={})

    def role_update(self, _r: Any, body: Any, pid: str, key: str) -> httpx.Response:
        self.roles[(pid, key)].update(body)
        return httpx.Response(200, json={})

    # -- apps -----------------------------------------------------------------------------
    def app_search(self, _r: Any, body: Any, pid: str) -> httpx.Response:
        name = body["queries"][0]["nameQuery"]["name"]
        found = [
            {"id": aid, "name": a["name"], a["kind"]: {"clientId": a["clientId"], **a["config"]}}
            for aid, a in self.apps.items()
            if a["pid"] == pid and a["name"] == name
        ]
        return httpx.Response(200, json={"result": found})

    def _app(self, pid: str, body: Any, kind: str, secret: bool) -> httpx.Response:
        aid = self.new_id()
        cfg = {k: v for k, v in body.items() if k != "name"}
        app = {"pid": pid, "name": body["name"], "kind": kind, "clientId": f"c{aid}", "config": cfg}
        if secret:
            app["secret"] = f"s{aid}-{self.new_id()}"
        self.apps[aid] = app
        out = {"appId": aid, "clientId": app["clientId"]}
        if secret:
            out["clientSecret"] = app["secret"]
        return httpx.Response(200, json=out)

    def oidc_create(self, _r: Any, body: Any, pid: str) -> httpx.Response:
        return self._app(pid, body, "oidcConfig", body["authMethodType"] != "OIDC_AUTH_METHOD_TYPE_NONE")

    def api_create(self, _r: Any, body: Any, pid: str) -> httpx.Response:
        return self._app(pid, body, "apiConfig", True)

    def app_update(self, _r: Any, body: Any, _pid: str, aid: str, _kind: str) -> httpx.Response:
        if self.apps[aid]["config"] == body:
            return httpx.Response(400, json={"code": 9, "message": "No changes (COMMAND-1m88i)"})
        self.apps[aid]["config"] = dict(body)
        return httpx.Response(200, json={})

    def app_secret(self, _r: Any, _b: Any, _pid: str, aid: str) -> httpx.Response:
        self.apps[aid]["secret"] = f"s{aid}-{self.new_id()}"
        return httpx.Response(200, json={"clientSecret": self.apps[aid]["secret"]})

    # -- users, keys, members ------------------------------------------------------------
    def user_search(self, _r: Any, body: Any) -> httpx.Response:
        q = body["queries"][0]["userNameQuery"]
        match = (
            (lambda n: n == q["userName"])
            if q["method"].endswith("EQUALS")
            else lambda n: n.startswith(q["userName"])
        )
        result = [
            {k: v for k, v in u.items() if k != "keys"} for u in self.users.values() if match(u["userName"])
        ]
        return httpx.Response(200, json={"result": result})

    def user_create(self, _r: Any, body: Any) -> httpx.Response:
        uid = self.new_id()
        self.users[uid] = {"id": uid, "userName": body["userName"], "machine": {}, "keys": set()}
        return httpx.Response(200, json={"userId": uid})

    def key_search(self, _r: Any, _b: Any, uid: str) -> httpx.Response:
        return httpx.Response(200, json={"result": [{"id": k} for k in sorted(self.users[uid]["keys"])]})

    def key_create(self, _r: Any, _b: Any, uid: str) -> httpx.Response:
        kid = self.new_id()
        self.users[uid]["keys"].add(kid)
        details = base64.b64encode(_key_json(uid, kid).encode()).decode()
        return httpx.Response(200, json={"keyId": kid, "keyDetails": details})

    def key_delete(self, _r: Any, _b: Any, uid: str, kid: str) -> httpx.Response:
        self.users[uid]["keys"].discard(kid)
        return httpx.Response(200, json={})

    def member_search(self, _r: Any, body: Any) -> httpx.Response:
        uid = body["queries"][0]["userIdQuery"]["userId"]
        found = [{"userId": uid, "roles": self.members[uid]}] if uid in self.members else []
        return httpx.Response(200, json={"result": found})

    def member_create(self, _r: Any, body: Any) -> httpx.Response:
        if body["userId"] in self.members:
            return httpx.Response(409, json={"message": "Errors.IAM.Member.AlreadyExists"})
        self.members[body["userId"]] = body["roles"]
        return httpx.Response(200, json={})

    # -- organizations and grants --------------------------------------------------------
    def org_search(self, _r: Any, body: Any) -> httpx.Response:
        name = body["queries"][0]["nameQuery"]["name"]
        return httpx.Response(
            200, json={"result": [{"id": i, "name": n} for i, n in self.orgs.items() if n == name]}
        )

    def org_create(self, _r: Any, body: Any) -> httpx.Response:
        if body["name"] in self.orgs.values():
            return httpx.Response(409, json={"message": "Organisation already exists"})
        oid = self.new_id()
        self.orgs[oid] = body["name"]
        return httpx.Response(201, json={"organizationId": oid})

    def grant_search(self, _r: Any, _b: Any, _pid: str) -> httpx.Response:
        return httpx.Response(200, json={"result": list(self.grants.values())})

    def grant_create(self, _r: Any, body: Any, _pid: str) -> httpx.Response:
        gid = self.new_id()
        self.grants[gid] = {
            "grantId": gid,
            "grantedOrgId": body["grantedOrgId"],
            "grantedRoleKeys": body["roleKeys"],
        }
        return httpx.Response(200, json={"grantId": gid})

    def grant_update(self, _r: Any, body: Any, _pid: str, gid: str) -> httpx.Response:
        self.grants[gid]["grantedRoleKeys"] = body["roleKeys"]
        return httpx.Response(200, json={})

    def policy_update(self, _r: Any, body: Any) -> httpx.Response:
        self.policy.update(body)
        return httpx.Response(200, json={})


class FakeOpenBao:
    def __init__(self) -> None:
        self.kv: dict[str, dict[str, Any]] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["x-vault-token"] == "op-token"
        path = request.url.path.removeprefix("/v1/secret/data/")
        if request.method == "GET":
            if path not in self.kv:
                return httpx.Response(404, json={"errors": []})
            return httpx.Response(200, json={"data": {"data": self.kv[path]}})
        self.kv[path] = json.loads(request.content)["data"]
        return httpx.Response(200, json={})


# ---------------------------------------------------------------- fixtures


@pytest.fixture
def root(tmp_path: Path) -> Path:
    shutil.copytree(REPO / "config" / "organizations", tmp_path / "config" / "organizations")
    (tmp_path / "bootstrap").mkdir()
    (tmp_path / "bootstrap" / "bootstrap-key.json").write_text(_key_json("boot", "k0"), encoding="utf-8")
    return tmp_path


def settings_for(root: Path, env: str = "development", **extra: Any) -> bz.Settings:
    s = bz.Settings.from_env(
        {
            "ASSETFLOW_ENV": env,
            "ASSETFLOW_ROOT": str(root),
            "ZITADEL_BOOTSTRAP_URL": "http://zitadel:8080",
            "ZITADEL_FIRSTINSTANCE_KEY_FILE": str(root / "bootstrap" / "bootstrap-key.json"),
            "ZITADEL_FIRSTINSTANCE_PAT_FILE": str(root / "bootstrap" / "bootstrap.pat"),
        }
    )
    s.ready_timeout = 1
    for k, v in extra.items():
        setattr(s, k, v)
    return s


def run(
    fake: FakeZitadel, settings: bz.Settings, store: bz.SecretStore | None = None
) -> tuple[dict, list[str]]:
    lines: list[str] = []
    client = httpx.Client(base_url=settings.bootstrap_url, transport=httpx.MockTransport(fake))
    zitadel = bz.Zitadel(settings, client)
    store = store or bz.make_store(settings, {})
    results = bz.Bootstrap(settings, zitadel, store, out=lines.append).run()
    return results, lines


# ---------------------------------------------------------------- tests


def test_first_run_creates_everything_and_writes_env_local(root: Path) -> None:
    fake = FakeZitadel()
    s = settings_for(root)
    _, lines = run(fake, s)

    assert len(fake.projects) == 1
    project = next(iter(fake.projects.values()))
    assert project["projectRoleAssertion"] is True
    assert {k for _, k in fake.roles} == set(bz.DEFAULT_ROLES)
    apps = {a["name"]: a for a in fake.apps.values()}
    web = apps["assetflow-web"]["config"]
    assert web["appType"] == "OIDC_APP_TYPE_USER_AGENT"
    assert web["authMethodType"] == "OIDC_AUTH_METHOD_TYPE_NONE"
    assert web["accessTokenType"] == "OIDC_TOKEN_TYPE_JWT"
    assert web["accessTokenRoleAssertion"] and web["idTokenRoleAssertion"]
    assert web["grantTypes"] == ["OIDC_GRANT_TYPE_AUTHORIZATION_CODE", "OIDC_GRANT_TYPE_REFRESH_TOKEN"]
    assert web["redirectUris"] == ["http://localhost:5173/auth/callback"]
    assert apps["assetflow-bff"]["config"]["authMethodType"] == "OIDC_AUTH_METHOD_TYPE_BASIC"
    assert apps["assetflow-introspection"]["kind"] == "apiConfig"
    assert fake.members[
        next(u for u, v in fake.users.items() if v["userName"] == "assetflow-automation")
    ] == ["IAM_ORG_MANAGER"]
    # The public Host header is sent although the URL is the internal one.
    assert fake.hosts == {"localhost:19081"}

    env = bz.EnvFile(root / ".env.local").read()
    assert env["ZITADEL_PROJECT_ID"] == project["id"]
    assert env["ZITADEL_ISSUER"] == ISSUER
    assert env["ZITADEL_WEB_CLIENT_ID"] == apps["assetflow-web"]["clientId"]
    assert env["ZITADEL_BFF_CLIENT_SECRET"] == apps["assetflow-bff"]["secret"]
    assert env["ZITADEL_INTROSPECTION_CLIENT_SECRET"] == apps["assetflow-introspection"]["secret"]
    service_key = json.loads(base64.b64decode(env["ZITADEL_SERVICE_ACCOUNT_KEY"]))
    assert service_key["keyId"] in fake.users[service_key["userId"]]["keys"]
    # No secret value is printed.
    printed = "\n".join(lines)
    assert apps["assetflow-bff"]["secret"] not in printed
    assert "admin login: admin@assetflow-platform.localhost" in printed


def test_second_run_changes_nothing(root: Path) -> None:
    fake = FakeZitadel()
    s = settings_for(root)
    run(fake, s)
    env_before = (root / ".env.local").read_text(encoding="utf-8")
    fake.calls.clear()
    fake.statuses.clear()

    _, lines = run(fake, s)

    assert fake.mutations == [], fake.mutations
    assert lines[-1] == "==> No changes."
    assert (root / ".env.local").read_text(encoding="utf-8") == env_before


def test_first_instance_key_is_rotated_and_deleted(root: Path) -> None:
    fake = FakeZitadel()
    key_file = root / "bootstrap" / "bootstrap-key.json"
    run(fake, settings_for(root))

    assert not key_file.exists()
    assert "k0" not in fake.users["boot"]["keys"]  # the key that sat on the volume is revoked
    assert ("DELETE", "/management/v1/users/boot/keys/k0") in fake.calls
    stored = json.loads(base64.b64decode(bz.EnvFile(root / ".env.local").read()["ZITADEL_BOOTSTRAP_KEY"]))
    assert stored["userId"] == "boot" and stored["keyId"] in fake.users["boot"]["keys"]


def test_conflict_409_counts_as_success(root: Path) -> None:
    fake = FakeZitadel(conflict_on_role_create=True)
    _, lines = run(fake, settings_for(root))
    assert {k for _, k in fake.roles} == set(bz.DEFAULT_ROLES)
    assert "  ok: role viewer exists" in lines


def test_organizations_and_project_grants(root: Path) -> None:
    fake = FakeZitadel()
    results, lines = run(fake, settings_for(root))

    by_name = {n: i for i, n in fake.orgs.items()}
    alpha, beta = by_name["Example Alpha"], by_name["Example Beta"]
    grants = {g["grantedOrgId"]: g["grantedRoleKeys"] for g in fake.grants.values()}
    assert grants[beta] == ["viewer", "technician", "asset_manager", "admin"]
    assert set(grants[alpha]) == set(bz.DEFAULT_ROLES)
    assert results["ZITADEL_ORGANIZATIONS"] == f"example-alpha:{alpha},example-beta:{beta}"
    assert f"==> organization example-beta: idp_organization_id {beta}" in lines

    # Roles changed in the organization file are re-applied to the existing grant.
    path = root / "config" / "organizations" / "example-beta.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("    - asset_manager\n", ""), encoding="utf-8")
    fake.calls.clear()
    fake.statuses.clear()
    run(fake, settings_for(root))
    assert {g["grantedOrgId"]: g["grantedRoleKeys"] for g in fake.grants.values()}[beta] == [
        "viewer",
        "technician",
        "admin",
    ]
    assert not [c for c in fake.mutations if c[0] == "POST"]


def test_invalid_organization_file_is_rejected(root: Path) -> None:
    path = root / "config" / "organizations" / "example-beta.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("    - viewer\n", "    - superuser\n"), encoding="utf-8"
    )
    with pytest.raises(bz.BootstrapError, match="unknown: superuser"):
        run(FakeZitadel(), settings_for(root))


def test_dry_run_changes_nothing(root: Path) -> None:
    fake = FakeZitadel()
    _, lines = run(fake, settings_for(root, dry_run=True))
    assert fake.mutations == []
    assert not (root / ".env.local").exists()
    assert (root / "bootstrap" / "bootstrap-key.json").exists()
    assert "  would create: project AssetFlow" in lines
    assert lines[-1].startswith("==> Dry run:")


def test_stale_stored_secret_is_replaced(root: Path) -> None:
    fake = FakeZitadel()
    s = settings_for(root)
    run(fake, s)
    env = bz.EnvFile(root / ".env.local")
    env.update({"ZITADEL_INTROSPECTION_CLIENT_SECRET": "wrong"})
    run(fake, s)
    app = next(a for a in fake.apps.values() if a["name"] == "assetflow-introspection")
    assert env.read()["ZITADEL_INTROSPECTION_CLIENT_SECRET"] == app["secret"] != "wrong"


def test_production_writes_openbao_and_never_files(root: Path) -> None:
    fake, bao = FakeZitadel(), FakeOpenBao()
    s = settings_for(root, env="production")
    store = bz.OpenBaoStore(
        "https://openbao:8200",
        "op-token",
        None,
        client=httpx.Client(base_url="https://openbao:8200", transport=httpx.MockTransport(bao)),
    )
    run(fake, s, store)

    assert not (root / ".env.local").exists()
    assert sorted(p.name for p in root.iterdir()) == ["bootstrap", "config"]
    idp = bao.kv["assetflow/idp"]
    assert idp["project_id"] == next(iter(fake.projects))
    assert (
        idp["client_secret"] == next(a for a in fake.apps.values() if a["name"] == "assetflow-bff")["secret"]
    )
    assert json.loads(bao.kv["assetflow/zitadel/bootstrap-key"]["key_json"])["userId"] == "boot"
    assert set(bao.kv["assetflow/zitadel/organizations"]) == {"example-alpha", "example-beta"}
    assert "keyId" in json.loads(bao.kv["assetflow/zitadel/automation-key"]["key_json"])
    # Strict login policy in production; redirect URIs without dev mode.
    assert fake.policy["forceMfa"] is True and fake.policy["allowRegister"] is False
    assert all(a["config"].get("devMode") is False for a in fake.apps.values() if a["kind"] == "oidcConfig")

    fake.calls.clear()
    fake.statuses.clear()
    _, lines = run(fake, s, store)
    assert fake.mutations == [] and lines[-1] == "==> No changes."


def test_production_refuses_file_store(root: Path) -> None:
    s = settings_for(root, env="production")
    with pytest.raises(bz.BootstrapError, match="never writes secrets to files"):
        bz.DevEnvStore(root / ".env.local", s)
    with pytest.raises(bz.BootstrapError, match="BAO_TOKEN"):
        bz.make_store(s, {})
    assert isinstance(bz.make_store(s, {"BAO_TOKEN": "op-token"}), bz.OpenBaoStore)
    with pytest.raises(bz.BootstrapError, match="local development only"):
        bz.init_env(s, None)
    assert not (root / ".env.local").exists()


def test_init_env_generates_reuses_and_detects_other_masterkey(root: Path) -> None:
    s = settings_for(root)
    marker_dir = root / "bootstrap"
    bz.init_env(s, marker_dir, out=lambda _: None)
    env = bz.EnvFile(root / ".env.local")
    first = env.read()
    assert set(bz.DEV_SECRETS) <= set(first)
    assert len(first["ZITADEL_MASTERKEY"]) == 32
    password = first["ZITADEL_ADMIN_PASSWORD"]
    assert len(password) == 32 and "$" not in password and "%" not in password
    assert any(c.isupper() for c in password) and any(c.islower() for c in password)
    assert any(c.isdigit() for c in password) and any(not c.isalnum() for c in password)

    bz.init_env(s, marker_dir, out=lambda _: None)
    assert env.read() == first  # reused on re-runs

    (root / ".env.local").unlink()  # secrets lost, volume kept
    with pytest.raises(bz.BootstrapError, match="different masterkey"):
        bz.init_env(s, marker_dir, out=lambda _: None)
    assert "ZITADEL_MASTERKEY" not in env.read()


def test_env_file_keeps_other_lines(tmp_path: Path) -> None:
    path = tmp_path / ".env.local"
    path.write_text("# mine\nOTHER=1\nZITADEL_PROJECT_ID=old\n", encoding="utf-8")
    changed = bz.EnvFile(path).update({"ZITADEL_PROJECT_ID": "new", "ZITADEL_URL": "http://x"})
    assert changed == ["ZITADEL_PROJECT_ID", "ZITADEL_URL"]
    assert (
        path.read_text(encoding="utf-8")
        == "# mine\nOTHER=1\nZITADEL_PROJECT_ID=new\n\nZITADEL_URL=http://x\n"
    )
    with pytest.raises(bz.BootstrapError, match="single line"):
        bz.EnvFile(path).update({"X": "a\nb"})
