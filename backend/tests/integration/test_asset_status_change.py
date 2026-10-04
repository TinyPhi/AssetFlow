# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Asset status change and available transitions (§B8.1, §C4.3, §C4.5, P8-08), against a real
disposable PostgreSQL: every declared transition of both shipped templates over HTTP, refusals
(invalid transition, reason, condition, reserved status, permission, scope, stale version), audit
event and outbox row."""

from __future__ import annotations

import json
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
TEMPLATES = ("it-assets", "facilities")


def _declared(key: str) -> list[tuple[str, str, str, bool]]:
    raw = yaml.safe_load((DOMAINS / f"{key}.yaml").read_text(encoding="utf-8"))["assets"]
    return [(key, t["from"], t["to"], bool(t.get("requires_reason"))) for t in raw["transitions"]]


ALL_DECLARED = [row for key in TEMPLATES for row in _declared(key)]


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


def _headers(org_id: UUID, role: str = "admin") -> dict[str, str]:
    return {"x-member-id": str(uuid4()), "x-organization-id": str(org_id), "x-role": role}


async def _create_org(pool: Pool, domain_key: str) -> UUID:
    org_id = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.organizations"
            " (id, slug, name, idp_organization_id, domain_key, settings)"
            " VALUES ($1, $2, 'Status Org', $3, $4, '{}'::jsonb)",
            org_id,
            f"status-{org_id.hex[:12]}",
            f"idp-status-{uuid4().hex[:12]}",
            domain_key,
        )
        await install_module(conn, org_id, "assets")
    return org_id


async def _make_asset(
    client: httpx.AsyncClient, pool: Pool, domain_key: str = "it-assets"
) -> tuple[UUID, UUID, str]:
    org_id = await _create_org(pool, domain_key)
    unit_id, category_id = uuid4(), uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.org_units (id, organization_id, parent_id, path, type, code, name) "
            "VALUES ($1, $2, NULL, $3::ltree, 'unit', $3, $3)",
            unit_id,
            org_id,
            _token(),
        )
        await conn.execute(
            "INSERT INTO public.asset_categories "
            "(id, organization_id, parent_id, path, code, name, default_criticality, tag_prefix) "
            "VALUES ($1, $2, NULL, $3::ltree, $3, $3, 'medium', NULL)",
            category_id,
            org_id,
            _token(),
        )
    res = await client.post(
        BASE,
        json={"name": "Thing", "category_id": str(category_id), "owner_org_unit_id": str(unit_id)},
        headers=_headers(org_id),
    )
    assert res.status_code == 201, res.text
    return org_id, unit_id, res.json()["data"]["id"]


async def _set_status(pool: Pool, org_id: UUID, asset_id: str, status: str) -> None:
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "UPDATE public.assets SET status = $1 WHERE organization_id = $2 AND id = $3",
            status,
            org_id,
            UUID(asset_id),
        )


async def _set_holder_member(pool: Pool, org_id: UUID, asset_id: str) -> None:
    member_id = uuid4()
    async with tenant_transaction(pool, org_id) as conn:
        await conn.execute(
            "INSERT INTO public.members (id, organization_id, idp_subject, email, display_name, status) "
            "VALUES ($1, $2, $3, $4, 'Holder', 'active')",
            member_id,
            org_id,
            f"idp-{member_id.hex[:12]}",
            f"{member_id.hex[:12]}@example.test",
        )
        await conn.execute(
            "UPDATE public.assets SET holder_member_id = $1 WHERE organization_id = $2 AND id = $3",
            member_id,
            org_id,
            UUID(asset_id),
        )


def _change(to: str, version: int = 1, reason: str | None = None) -> dict[str, object]:
    body: dict[str, object] = {"to_status": to, "version": version}
    if reason is not None:
        body["reason"] = reason
    return body


@pytest.mark.parametrize(("key", "from_status", "to_status", "needs_reason"), ALL_DECLARED)
async def test_every_declared_transition_succeeds(
    client: httpx.AsyncClient,
    make_pool: PoolFactory,
    *,
    key: str,
    from_status: str,
    to_status: str,
    needs_reason: bool,
) -> None:
    pool = await make_pool("api")
    org_id, _, asset_id = await _make_asset(client, pool, key)
    await _set_status(pool, org_id, asset_id, from_status)

    res = await client.post(
        f"{BASE}/{asset_id}/change-status",
        json=_change(to_status, reason="end of life" if needs_reason else None),
        headers=_headers(org_id),
    )
    assert res.status_code == 200, res.text
    assert res.json()["data"]["status"] == to_status
    assert res.json()["data"]["version"] == 2


async def test_success_writes_audit_event_and_outbox_row(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id, _, asset_id = await _make_asset(client, pool)

    res = await client.post(
        f"{BASE}/{asset_id}/change-status",
        json=_change("retired", reason="  beyond repair  "),
        headers=_headers(org_id),
    )
    assert res.status_code == 200, res.text

    async with tenant_transaction(pool, org_id) as conn:
        audit = await conn.fetchrow(
            "SELECT before_state, after_state FROM public.audit_events "
            "WHERE organization_id = $1 AND entity_id = $2 AND action = 'asset.status_changed'",
            org_id,
            UUID(asset_id),
        )
        outbox = await conn.fetchrow(
            "SELECT payload FROM public.outbox "
            "WHERE organization_id = $1 AND aggregate_id = $2 AND event_type = 'asset.status_changed'",
            org_id,
            UUID(asset_id),
        )
    assert audit is not None
    assert json.loads(audit["before_state"]) == {"status": "in_stock"}
    assert json.loads(audit["after_state"]) == {"status": "retired", "reason": "beyond repair"}
    assert outbox is not None
    payload = json.loads(outbox["payload"])
    assert payload == {
        "id": asset_id,
        "from_status": "in_stock",
        "to_status": "retired",
        "reason": "beyond repair",
        "version": 2,
    }


async def test_invalid_transition_is_409_and_changes_nothing(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id, _, asset_id = await _make_asset(client, pool)

    res = await client.post(
        f"{BASE}/{asset_id}/change-status", json=_change("in_repair"), headers=_headers(org_id)
    )
    assert res.status_code == 409
    body = res.json()
    assert body["code"] == "asset.invalid_transition"
    assert '"in_stock"' in body["detail"]
    assert '"in_repair"' in body["detail"]

    async with tenant_transaction(pool, org_id) as conn:
        row = await conn.fetchrow(
            "SELECT status, version FROM public.assets WHERE organization_id = $1 AND id = $2",
            org_id,
            UUID(asset_id),
        )
        audits = await conn.fetchval(
            "SELECT count(*) FROM public.audit_events "
            "WHERE organization_id = $1 AND action = 'asset.status_changed'",
            org_id,
        )
    assert row is not None
    assert (row["status"], row["version"]) == ("in_stock", 1)
    assert audits == 0


@pytest.mark.parametrize("target", ["nonsense", "under_maintenance"])
async def test_unknown_and_reserved_targets_are_409(
    client: httpx.AsyncClient, make_pool: PoolFactory, target: str
) -> None:
    pool = await make_pool("api")
    org_id, _, asset_id = await _make_asset(client, pool)
    res = await client.post(
        f"{BASE}/{asset_id}/change-status", json=_change(target), headers=_headers(org_id)
    )
    assert res.status_code == 409
    assert res.json()["code"] == "asset.invalid_transition"


async def test_missing_reason_is_409(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id, _, asset_id = await _make_asset(client, pool)
    res = await client.post(
        f"{BASE}/{asset_id}/change-status", json=_change("retired"), headers=_headers(org_id)
    )
    assert res.status_code == 409
    assert res.json()["code"] == "asset.invalid_transition"
    assert "reason" in res.json()["detail"]


async def test_cannot_retire_an_asset_that_has_a_holder(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id, _, asset_id = await _make_asset(client, pool)
    await _set_holder_member(pool, org_id, asset_id)
    res = await client.post(
        f"{BASE}/{asset_id}/change-status", json=_change("retired", reason="old"), headers=_headers(org_id)
    )
    assert res.status_code == 409
    assert res.json()["code"] == "asset.invalid_transition"
    assert "holder" in res.json()["detail"]


async def test_stale_version_is_409_version_conflict(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id, _, asset_id = await _make_asset(client, pool)
    res = await client.post(
        f"{BASE}/{asset_id}/change-status", json=_change("in_service", version=7), headers=_headers(org_id)
    )
    assert res.status_code == 409
    assert res.json()["code"] == "asset.version_conflict"


async def test_caller_without_permission_is_403(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id, _, asset_id = await _make_asset(client, pool)
    res = await client.post(
        f"{BASE}/{asset_id}/change-status",
        json=_change("in_service"),
        headers=_headers(org_id, role="planner"),
    )
    assert res.status_code == 403
    assert res.json()["code"] == "auth.permission_denied"


async def test_caller_outside_scope_gets_404_on_read_and_403_on_the_action(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id, _, asset_id = await _make_asset(client, pool)
    headers = {
        **_headers(org_id, role="asset_manager"),
        "x-scope-type": "org_unit",
        "x-org-unit-path": uuid4().hex[:10],  # a different unit: never covers the asset
    }
    read = await client.get(f"{BASE}/{asset_id}", headers=headers)
    assert read.status_code == 404
    act = await client.post(f"{BASE}/{asset_id}/change-status", json=_change("in_service"), headers=headers)
    assert act.status_code == 403
    listing = await client.get(f"{BASE}/{asset_id}/transitions", headers=headers)
    assert listing.status_code == 404


async def test_unknown_asset_is_404(client: httpx.AsyncClient, make_pool: PoolFactory) -> None:
    pool = await make_pool("api")
    org_id, _, _ = await _make_asset(client, pool)
    res = await client.post(
        f"{BASE}/{uuid4()}/change-status", json=_change("in_service"), headers=_headers(org_id)
    )
    assert res.status_code == 404


async def test_transitions_lists_what_the_caller_may_take_now(
    client: httpx.AsyncClient, make_pool: PoolFactory
) -> None:
    pool = await make_pool("api")
    org_id, _, asset_id = await _make_asset(client, pool)

    res = await client.get(f"{BASE}/{asset_id}/transitions", headers=_headers(org_id))
    assert res.status_code == 200, res.text
    items = {i["to_status"]: i for i in res.json()["data"]["items"]}
    assert set(items) == {"assigned", "in_service", "retired", "lost", "disposed"}
    assert items["retired"]["requires_reason"] is True
    assert items["in_service"]["requires_reason"] is False

    await _set_holder_member(pool, org_id, asset_id)
    held = await client.get(f"{BASE}/{asset_id}/transitions", headers=_headers(org_id))
    assert {i["to_status"] for i in held.json()["data"]["items"]} == {"assigned", "in_service"}

    limited = await client.get(f"{BASE}/{asset_id}/transitions", headers=_headers(org_id, role="planner"))
    assert limited.json()["data"]["items"] == []
