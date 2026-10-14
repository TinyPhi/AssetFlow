# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Unit tests for audit helper, personal field redaction, and housekeeping logic (§1590, §2138)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.audit.housekeeping import next_month_name
from app.modules.audit.service import erase_personal_values, record_audit_event, redact_personal_fields


def test_redact_personal_fields_extracts_and_replaces() -> None:
    coll: dict[str, str] = {}
    st = {"email": "a@ex.com", "code": "HQ", "sub": {"ip": "1.1.1.1"}}
    assert redact_personal_fields(st, coll) == {
        "email": "[REDACTED]",
        "code": "HQ",
        "sub": {"ip": "[REDACTED]"},
    }
    assert coll == {"email": "a@ex.com", "ip": "1.1.1.1"}


def test_next_month_name_formatting() -> None:
    assert next_month_name(datetime(2026, 10, 15, tzinfo=UTC)) == "audit_events_2026_11"
    assert next_month_name(datetime(2026, 12, 1, tzinfo=UTC)) == "audit_events_2027_01"


@pytest.mark.anyio
async def test_record_audit_event_writes_event_and_personal_values() -> None:
    conn = AsyncMock()
    ev_id = await record_audit_event(
        conn,
        organization_id=uuid4(),
        action="member.create",
        entity_type="member",
        entity_id=uuid4(),
        after_state={"name": "Alice", "email": "alice@ex.com"},
    )
    assert ev_id is not None and conn.execute.call_count == 3


@pytest.mark.anyio
async def test_erase_personal_values_executes_delete() -> None:
    conn = AsyncMock()
    conn.execute.return_value = "DELETE 2"
    assert await erase_personal_values(conn, organization_id=uuid4(), audit_event_id=uuid4()) == 2
