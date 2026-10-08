# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The audit events route: per-organization scope and the platform-admin cross-org view (§B5.3, §B10)."""

from __future__ import annotations

from uuid import uuid4

import httpx
from pg_harness import IsolationDb, PoolFactory

from app.core.db import tenant_transaction
from app.main import create_app
from app.modules.audit.service import record_audit_event


async def test_audit_api_scope_isolation_and_platform_admin(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    api_pool = await make_pool("api")
    app = create_app()
    app.state.pool = api_pool
    ea, eb = uuid4(), uuid4()

    for org, ev in ((isolation_db.org_a, ea), (isolation_db.org_b, eb)):
        async with tenant_transaction(api_pool, org) as conn:
            await record_audit_event(
                conn, organization_id=org, action="a", entity_type="e", entity_id=uuid4(), event_id=ev
            )

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        hdr_a = {"x-member-id": str(uuid4()), "x-organization-id": str(isolation_db.org_a), "x-role": "admin"}
        res = await c.get("/api/v1/audit/events", headers=hdr_a)
        assert res.status_code == 200 and str(ea) in [i["id"] for i in res.json()["data"]]

        hdr_lim = {**hdr_a, "x-role": "member", "x-scope-type": "self"}
        assert (await c.get("/api/v1/audit/events", headers=hdr_lim)).status_code == 404

        hdr_adm = {"x-platform-admin": "true"}
        assert (await c.get("/api/v1/audit/events", headers=hdr_adm)).status_code in (400, 422)

        r_adm = await c.get(f"/api/v1/audit/events?organization_id={isolation_db.org_a}", headers=hdr_adm)
        assert r_adm.status_code == 200 and str(ea) in [i["id"] for i in r_adm.json()["data"]]
