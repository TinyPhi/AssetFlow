# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The automation planner against a real PostgreSQL (§B6.3, M1.5-T2)."""

from __future__ import annotations

import uuid

from pg_harness import IsolationDb, PoolFactory
from tenant_checks import token

from app.core.db import Pool, tenant_transaction
from app.engines.automation.directory_pg import PgDirectory
from app.engines.automation.models import AutomationRule
from app.engines.automation.planner import plan
from app.modules.event_registry import default_event_registry as default_registry
from app.modules.organization.events import TEAM_MEMBER_ADDED

RULE = AutomationRule.model_validate(
    {
        "when": TEAM_MEMBER_ADDED,
        "then": {"recipients": ["holder"], "channels": ["inapp"], "template": "team-member-added"},
    }
)


async def _insert_member(pool: Pool, organization_id: uuid.UUID) -> uuid.UUID:
    member_id = uuid.uuid4()
    async with tenant_transaction(pool, organization_id) as conn:
        await conn.execute(
            "INSERT INTO public.members (id, organization_id, idp_subject, email, display_name, status) "
            "VALUES ($1, $2, $3, $4, 'Test Member', 'active')",
            member_id,
            organization_id,
            f"idp-{token()}",
            f"{token()}@example.org",
        )
    return member_id


async def test_one_event_produces_the_expected_intents_with_stable_idempotency_keys(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    api = await make_pool("api")
    member_id = await _insert_member(api, isolation_db.org_a)
    event_id = uuid.uuid4()
    event_data = {
        "id": str(uuid.uuid4()),
        "team_id": str(uuid.uuid4()),
        "member_id": str(member_id),
        "team_role": "member",
    }

    worker = await make_pool("worker")
    async with tenant_transaction(worker, isolation_db.org_a) as conn:
        directory = PgDirectory(conn)
        intents = await plan(
            event_id=event_id,
            organization_id=isolation_db.org_a,
            event_type=TEAM_MEMBER_ADDED,
            event_data=event_data,
            rules=[RULE],
            registry=default_registry(),
            directory=directory,
        )

    assert len(intents) == 1
    (intent,) = intents
    assert intent.event_id == event_id
    assert intent.organization_id == isolation_db.org_a
    assert intent.member_id == member_id
    assert intent.channel_key == "inapp"
    assert intent.template_key == "team-member-added"

    # Running the same event again produces the exact same idempotency key.
    async with tenant_transaction(worker, isolation_db.org_a) as conn:
        again = await plan(
            event_id=event_id,
            organization_id=isolation_db.org_a,
            event_type=TEAM_MEMBER_ADDED,
            event_data=event_data,
            rules=[RULE],
            registry=default_registry(),
            directory=PgDirectory(conn),
        )
    assert len(again) == 1
    assert again[0].idempotency_key == intent.idempotency_key


async def test_org_a_rules_never_resolve_org_b_members(
    make_pool: PoolFactory, isolation_db: IsolationDb
) -> None:
    # The event claims a member id that only exists under org_b; resolving it while stamped as
    # org_a must see nothing, because row-level security hides org_b's row entirely.
    member_b = await _insert_member(await make_pool("api"), isolation_db.org_b)
    event_data = {
        "id": str(uuid.uuid4()),
        "team_id": str(uuid.uuid4()),
        "member_id": str(member_b),
        "team_role": "member",
    }
    worker = await make_pool("worker")
    async with tenant_transaction(worker, isolation_db.org_a) as conn:
        intents = await plan(
            event_id=uuid.uuid4(),
            organization_id=isolation_db.org_a,
            event_type=TEAM_MEMBER_ADDED,
            event_data=event_data,
            rules=[RULE],
            registry=default_registry(),
            directory=PgDirectory(conn),
        )
    assert intents == []
