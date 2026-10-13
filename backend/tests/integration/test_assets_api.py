# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Asset API: create, edit, detail (M2.1-T5, §B8.1, P8-07 part a), against a real disposable
PostgreSQL. Covers tag generation, initial status, default criticality, scope-denied create/edit,
version conflicts, forbidden-field refusal, 404 outside scope, audit+outbox, and Idempotency-Key
replay."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
import yaml
from pg_harness import PoolFactory

from app.core.db import Pool, tenant_transaction
from app.main import create_app
from app.modules.organization.modules import install_module
from app.providers.auth.mock import MockAuthProvider
from app.providers.context import ProviderContext
from app.providers.secrets.file import FileSecretsProvider
from app.providers.telemetry.noop import NoOpTelemetryProvider

BASE = "/api/v1/assets"
DOMAINS = Path(__file__).resolve().parents[3] / "config" / "domains"

_INSERT_ORG_UNIT = (
    "INSERT INTO public.org_units (id, organization_id, parent_id, path, type, code, name) "
    "VALUES ($1, $2, NULL, $3::ltree, 'unit', $3, $3)"
)
_INSERT_CATEGORY = (
    "INSERT INTO public.asset_categories "
    "(id, organization_id, parent_id, path, code, name, default_criticality, tag_prefix) "
    "VALUES ($1, $2, NULL, $3::ltree, $3, $3, $4, $5)"
)


class _Registry:
    def __init__(self, secrets: FileSecretsProvider) -> None:
        self.auth = MockAuthProvider(ProviderContext("test", "auth", Path()))
        self.telemetry = NoOpTelemetryProvider()
        self.secrets = secrets


@pytest.fixture
def secrets_provider(tmp_path: Path) -> FileSecretsProvider:
    context = ProviderContext(env="test", pillar="secrets", base_dir=tmp_path)
    return FileSecretsProvider.from_settings({"directory": "secrets"}, context)


@pytest.fixture
async def client(
    make_pool: PoolFactory, secrets_provider: FileSecretsProvider
) -> AsyncIterator[httpx.AsyncClient]:
    pool = await make_pool("api")
    app = create_app()
    app.state.pool = pool
    app.state.registry = _Registry(secrets_provider)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _token() -> str:
    return uuid4().hex[:10]


async def _create_org(pool: Pool, *, domain_key: str = "it-assets") -> UUID:
    org_id = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.organizations"
            " (id, slug, name, idp_organization_id, domain_key, settings)"
            " VALUES ($1, $2, 'Assets API Org', $3, $4, '{}'::jsonb)",
            org_id,
            f"assets-api-{org_id.hex[:12]}",
            f"idp-assets-api-{uuid4().hex[:12]}",
            domain_key,
        )
        await install_module(conn, org_id, "assets")
    return org_id


async def _make_org_unit(pool: Pool, org_id: UUID) -> UUID:
    unit_id = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(_INSERT_ORG_UNIT, unit_id, org_id, _token())
    return unit_id


async def _make_category(
    pool: Pool, org_id: UUID, *, default_criticality: str | None = "medium", tag_prefix: str | None = None
) -> UUID:
    category_id = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(_INSERT_CATEGORY, category_id, org_id, _token(), default_criticality, tag_prefix)
    return category_id


def _headers(org_id: UUID, role: str = "admin", member_id: UUID | None = None) -> dict[str, str]:
    return {
        "x-member-id": str(member_id or uuid4()),
        "x-organization-id": str(org_id),
        "x-role": role,
    }


async def _setup(pool: Pool) -> tuple[UUID, UUID, UUID]:
    org_id = await _create_org(pool)
    unit_id = await _make_org_unit(pool, org_id)
    category_id = await _make_category(pool, org_id)
    return org_id, unit_id, category_id


# ==============================================================================
# Create
# ==============================================================================


async def test_create_asset_generates_tag_initial_status_and_default_criticality(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id, unit_id, category_id = await _setup(pool)

    res = await client.post(
        BASE,
        json={"name": "Laptop 1", "category_id": str(category_id), "owner_org_unit_id": str(unit_id)},
        headers=_headers(org_id),
    )
    assert res.status_code == 201, res.text
    data = res.json()["data"]
    assert data["tag"].startswith("AST-")
    assert data["status"] == "in_stock"
    assert data["criticality"] == "medium"
    assert data["version"] == 1
    assert data["holder"] is None
    assert data["encrypted_fields"] == {}


async def test_create_outside_scope_is_denied(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id, unit_id, category_id = await _setup(pool)

    res = await client.post(
        BASE,
        json={"name": "Laptop 1", "category_id": str(category_id), "owner_org_unit_id": str(unit_id)},
        headers=_headers(org_id, role="member"),
    )
    assert res.status_code == 403
    assert res.json()["code"] == "auth.permission_denied"


async def test_create_audits_and_outboxes(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id, unit_id, category_id = await _setup(pool)

    res = await client.post(
        BASE,
        json={"name": "Laptop 1", "category_id": str(category_id), "owner_org_unit_id": str(unit_id)},
        headers=_headers(org_id),
    )
    asset_id = res.json()["data"]["id"]

    async with tenant_transaction(pool, org_id) as conn:
        action = await conn.fetchval(
            "SELECT action FROM public.audit_events WHERE organization_id = $1 AND entity_id = $2",
            org_id,
            UUID(asset_id),
        )
        event = await conn.fetchval(
            "SELECT event_type FROM public.outbox WHERE organization_id = $1 AND aggregate_id = $2",
            org_id,
            UUID(asset_id),
        )
    assert action == "asset.create"
    assert event == "asset.created"


async def test_idempotency_key_replay_returns_the_same_asset(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id, unit_id, category_id = await _setup(pool)
    headers = {**_headers(org_id), "Idempotency-Key": "replay-key-1"}

    body = {"name": "Laptop 1", "category_id": str(category_id), "owner_org_unit_id": str(unit_id)}
    first = await client.post(BASE, json=body, headers=headers)
    second = await client.post(BASE, json=body, headers=headers)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["data"]["id"] == second.json()["data"]["id"]
    assert first.json()["data"]["tag"] == second.json()["data"]["tag"]

    async with tenant_transaction(pool, org_id) as conn:
        count = await conn.fetchval("SELECT count(*) FROM public.assets WHERE organization_id = $1", org_id)
    assert count == 1


# ==============================================================================
# Edit
# ==============================================================================


async def test_edit_with_stale_version_is_conflict(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id, unit_id, category_id = await _setup(pool)
    create_res = await client.post(
        BASE,
        json={"name": "Laptop 1", "category_id": str(category_id), "owner_org_unit_id": str(unit_id)},
        headers=_headers(org_id),
    )
    asset_id = create_res.json()["data"]["id"]

    ok = await client.patch(
        f"{BASE}/{asset_id}", json={"name": "Laptop 2", "version": 1}, headers=_headers(org_id)
    )
    assert ok.status_code == 200
    assert ok.json()["data"]["name"] == "Laptop 2"
    assert ok.json()["data"]["version"] == 2

    stale = await client.patch(
        f"{BASE}/{asset_id}", json={"name": "Laptop 3", "version": 1}, headers=_headers(org_id)
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "asset.version_conflict"


async def test_edit_forbidden_fields_are_refused(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id, unit_id, category_id = await _setup(pool)
    create_res = await client.post(
        BASE,
        json={"name": "Laptop 1", "category_id": str(category_id), "owner_org_unit_id": str(unit_id)},
        headers=_headers(org_id),
    )
    asset_id = create_res.json()["data"]["id"]

    res = await client.patch(
        f"{BASE}/{asset_id}", json={"status": "retired", "version": 1}, headers=_headers(org_id)
    )
    assert res.status_code == 422
    assert res.json()["code"] == "validation.invalid_field"


# ==============================================================================
# Detail
# ==============================================================================


async def test_detail_404_outside_scope(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id, unit_id, category_id = await _setup(pool)
    other_unit_id = await _make_org_unit(pool, org_id)
    create_res = await client.post(
        BASE,
        json={"name": "Laptop 1", "category_id": str(category_id), "owner_org_unit_id": str(unit_id)},
        headers=_headers(org_id),
    )
    asset_id = create_res.json()["data"]["id"]

    headers = _headers(org_id, role="asset_manager")
    headers["x-scope-type"] = "org_unit"
    headers["x-org-unit-path"] = str(other_unit_id)  # wrong path shape on purpose: never matches

    res = await client.get(f"{BASE}/{asset_id}", headers=headers)
    assert res.status_code == 404
    assert res.json()["code"] == "asset.not_found"


async def test_detail_etag_matches_version_and_supports_if_none_match(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id, unit_id, category_id = await _setup(pool)
    create_res = await client.post(
        BASE,
        json={"name": "Laptop 1", "category_id": str(category_id), "owner_org_unit_id": str(unit_id)},
        headers=_headers(org_id),
    )
    asset_id = create_res.json()["data"]["id"]

    res = await client.get(f"{BASE}/{asset_id}", headers=_headers(org_id))
    assert res.status_code == 200
    etag = res.headers["etag"]
    assert etag == '"1"'

    cached = await client.get(f"{BASE}/{asset_id}", headers={**_headers(org_id), "if-none-match": etag})
    assert cached.status_code == 304


# ==============================================================================
# Scope refusals on writes (§C4.5: permission absent -> auth.permission_denied, record out of scope
# -> scope.denied)
# ==============================================================================


async def test_create_in_an_org_unit_outside_the_grant_is_scope_denied(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id, unit_id, category_id = await _setup(pool)
    headers = {
        **_headers(org_id, role="asset_manager"),
        "x-scope-type": "org_unit",
        "x-org-unit-path": "elsewhere",
    }
    res = await client.post(
        BASE,
        json={"name": "Laptop 1", "category_id": str(category_id), "owner_org_unit_id": str(unit_id)},
        headers=headers,
    )
    assert res.status_code == 403
    assert res.json()["code"] == "scope.denied"


async def test_edit_outside_the_grant_is_scope_denied(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id, unit_id, category_id = await _setup(pool)
    created = await client.post(
        BASE,
        json={"name": "Laptop 1", "category_id": str(category_id), "owner_org_unit_id": str(unit_id)},
        headers=_headers(org_id),
    )
    asset = created.json()["data"]
    headers = {
        **_headers(org_id, role="asset_manager"),
        "x-scope-type": "org_unit",
        "x-org-unit-path": "elsewhere",
    }
    res = await client.patch(
        f"{BASE}/{asset['id']}", json={"name": "x", "version": asset["version"]}, headers=headers
    )
    # Not readable from this scope either, so the existence of the record stays hidden or the
    # write is refused as out of scope; never the bare permission code.
    assert res.status_code in (403, 404)
    assert res.json()["code"] in ("scope.denied", "asset.not_found")


# ==============================================================================
# Vocabulary: the template's status labels and criticality levels (P8-11)
# ==============================================================================


@pytest.mark.parametrize("domain_key", ["it-assets", "facilities"])
async def test_vocabulary_serves_the_organizations_template(
    client: httpx.AsyncClient, make_pool: PoolFactory, domain_key: str
) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool, domain_key=domain_key)
    res = await client.get(f"{BASE}/vocabulary", headers=_headers(org_id, role="member"))
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    declared = yaml.safe_load((DOMAINS / f"{domain_key}.yaml").read_text(encoding="utf-8"))["assets"]
    assert [(s["key"], s["label"], s["category"]) for s in data["statuses"]] == [
        (s["key"], s["label"], s["category"]) for s in declared["statuses"]
    ]
    assert data["criticality"] == declared["criticality"]


async def test_vocabulary_differs_between_templates(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    it_org = await _create_org(pool, domain_key="it-assets")
    fac_org = await _create_org(pool, domain_key="facilities")
    it = (await client.get(f"{BASE}/vocabulary", headers=_headers(it_org))).json()["data"]
    fac = (await client.get(f"{BASE}/vocabulary", headers=_headers(fac_org))).json()["data"]
    assert it["criticality"] != fac["criticality"]
    assert {s["key"] for s in it["statuses"]} != {s["key"] for s in fac["statuses"]}


async def test_vocabulary_is_not_confused_with_an_asset_id(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    """`/vocabulary` is a fixed route, not `/{asset_id}`: it must not answer 422 for a non-UUID id."""
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    res = await client.get(f"{BASE}/vocabulary", headers=_headers(org_id))
    assert res.status_code == 200


async def test_vocabulary_needs_a_signed_in_caller_with_asset_read(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id = await _create_org(pool)
    anonymous = await client.get(f"{BASE}/vocabulary")
    assert anonymous.status_code == 401
    # `technician` reads assets; a role with no asset.read at all is refused.
    refused = await client.get(f"{BASE}/vocabulary", headers=_headers(org_id, role="no_such_role"))
    assert refused.status_code == 403
    assert refused.json()["code"] == "auth.permission_denied"


async def test_vocabulary_is_organization_scoped(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    """The route answers with the template of the caller's own organization only: an organization
    without a domain template gets an empty vocabulary, never another organization's."""
    pool = await make_pool("api")
    await _create_org(pool, domain_key="it-assets")
    other = uuid4()
    async with tenant_transaction(pool, other) as conn:
        await conn.execute(
            "INSERT INTO public.organizations (id, slug, name, idp_organization_id, domain_key, settings)"
            " VALUES ($1, $2, 'No Template Org', $3, 'generic', '{}'::jsonb)",
            other,
            f"no-template-{other.hex[:12]}",
            f"idp-no-template-{uuid4().hex[:12]}",
        )
        await install_module(conn, other, "assets")
    res = await client.get(f"{BASE}/vocabulary", headers=_headers(other))
    assert res.status_code == 200
    assert res.json()["data"] == {"statuses": [], "criticality": []}
