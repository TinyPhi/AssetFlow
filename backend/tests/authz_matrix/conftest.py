# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Fixtures for RBAC authorization matrix tests (§B11.6, §C8.4)."""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI

from app.core.cookie_crypto import derive_key
from app.core.permissions import ScopeType
from app.core.scope import MemberContext, RoleGrant
from app.main import Bootstrap, create_app
from app.providers.auth.mock import MockAuthProvider
from app.providers.context import ProviderContext

TEST_ORG_ID = "00000000-0000-0000-0000-000000000001"
TEST_MEMBER_ID = "00000000-0000-0000-0000-000000000001"


class MockRecord(dict):
    """A dictionary-backed mock for asyncpg.Record."""

    def __getitem__(self, key: str) -> Any:
        if key in self:
            return super().__getitem__(key)
        if "id" in key:
            return UUID(TEST_MEMBER_ID)
        if "name" in key:
            return "Test Name"
        if "status" in key:
            return "active"
        return None

    def __getattr__(self, name: str) -> Any:
        return self[name]


class DoubleTx:
    async def __aenter__(self) -> DoubleTx:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        pass


class DoubleConn:
    def transaction(self) -> DoubleTx:
        return DoubleTx()

    async def execute(self, *args: Any, **kwargs: Any) -> str:
        return "SELECT 1"

    async def fetch(self, query: str, *args: Any, **kwargs: Any) -> list[Any]:
        now = datetime.now(UTC)
        return [
            MockRecord(
                {
                    "id": UUID(TEST_MEMBER_ID),
                    "member_id": UUID(TEST_MEMBER_ID),
                    "organization_id": UUID(TEST_ORG_ID),
                    "parent_id": None,
                    "path": "test_path",
                    "display_name": "Test Member",
                    "name": "Test Entity",
                    "code": "test-code",
                    "type": "division",
                    "address": {},
                    "manager_member_id": None,
                    "owning_org_unit_id": None,
                    "working_calendar_id": None,
                    "skills": [],
                    "email": "user@example.org",
                    "phone": "+1234567890",
                    "status": "active",
                    "is_suspended": False,
                    "installed": True,
                    "version": 1,
                    "org_unit_id": UUID(TEST_MEMBER_ID),
                    "org_unit_name": "Engineering",
                    "team_id": UUID(TEST_MEMBER_ID),
                    "team_name": "Ops",
                    "team_role": "member",
                    "role_in_team": "technician",
                    "is_primary": True,
                    "role": "technician",
                    "role_key": "technician",
                    "target_member_id": UUID(TEST_MEMBER_ID),
                    "scope_type": "organization",
                    "scope_id": None,
                    "valid_from": now,
                    "valid_to": None,
                    "created_at": now,
                    "updated_at": now,
                    "event_type": "test.event",
                    "template_key": "test_template",
                    "title_key": "test_title",
                    "body": "test body",
                    "link_entity_type": None,
                    "link_entity_id": None,
                    "channel_key": "inapp",
                    "event_id": UUID(TEST_MEMBER_ID),
                    "recipient_member_id": UUID(TEST_MEMBER_ID),
                    "target": "user@example.org",
                    "attempts": 1,
                    "latency_ms": 10,
                    "error_code": None,
                    "next_retry_at": None,
                    "secret_fields_set": [],
                    "enabled": True,
                    "settings": {},
                    "events": [],
                    "allowed_hosts": [],
                    "allow_personal_data": False,
                    "read_at": None,
                    "tag_prefix": None,
                    "default_criticality": None,
                    "responsible_team_id": None,
                    "category_id": UUID(TEST_MEMBER_ID),
                    "key": "test_field",
                    "label": "Test Field",
                    "field_type": "text",
                    "is_required": False,
                    "rules": {},
                    "is_unique": False,
                    "is_encrypted": False,
                    "position": 0,
                    "contact": {},
                    "notes": None,
                    "tag": "AST-00001",
                    "category_name": "Test Category",
                    "model": None,
                    "manufacturer_id": None,
                    "manufacturer_name": None,
                    "supplier_id": None,
                    "supplier_name": None,
                    "serial_number": None,
                    "owner_org_unit_id": UUID(TEST_MEMBER_ID),
                    "owner_org_unit_name": "Test Org Unit",
                    "owner_org_unit_path": "test_path",
                    "location_id": None,
                    "location_name": None,
                    "holder_type": None,
                    "holder_id": None,
                    "holder_member_id": None,
                    "holder_team_id": None,
                    "component_id": UUID(TEST_MEMBER_ID),
                    "parent_asset_id": UUID(TEST_MEMBER_ID),
                    "child_asset_id": UUID(TEST_MEMBER_ID),
                    "attached_at": now,
                    "detached_at": None,
                    "holder_display_name": None,
                    "criticality": None,
                    "purchase_date": None,
                    "purchase_cost": None,
                    "warranty_end": None,
                    "custom_fields": {},
                    "encrypted_fields": {},
                    "idempotency_key": None,
                    "query": {},
                    "sort": "-created_at",
                    "columns": [],
                }
            )
        ]

    async def fetchrow(self, query: str, *args: Any, **kwargs: Any) -> Any:
        q_lower = query.lower()
        if "where code =" in q_lower or "where code=" in q_lower or "code = $" in q_lower:
            return None
        now = datetime.now(UTC)
        return MockRecord(
            {
                "id": UUID(TEST_MEMBER_ID),
                "member_id": UUID(TEST_MEMBER_ID),
                "organization_id": UUID(TEST_ORG_ID),
                "parent_id": None,
                "path": "test_path",
                "display_name": "Test Member",
                "name": "Test Entity",
                "code": "test-code",
                "type": "division",
                "address": {},
                "manager_member_id": None,
                "owning_org_unit_id": None,
                "working_calendar_id": None,
                "skills": [],
                "email": "user@example.org",
                "phone": "+1234567890",
                "status": "active",
                "is_suspended": False,
                "installed": True,
                "version": 1,
                "org_unit_id": UUID(TEST_MEMBER_ID),
                "org_unit_name": "Engineering",
                "team_id": UUID(TEST_MEMBER_ID),
                "team_name": "Ops",
                "team_role": "member",
                "role_in_team": "technician",
                "is_primary": True,
                "role": "technician",
                "role_key": "technician",
                "target_member_id": UUID(TEST_MEMBER_ID),
                "scope_type": "organization",
                "scope_id": None,
                "channel_key": "inapp",
                "event_id": UUID(TEST_MEMBER_ID),
                "recipient_member_id": UUID(TEST_MEMBER_ID),
                "target": "user@example.org",
                "attempts": 1,
                "latency_ms": 10,
                "error_code": None,
                "next_retry_at": None,
                "secret_fields_set": [],
                "enabled": True,
                "settings": {},
                "events": [],
                "allowed_hosts": [],
                "allow_personal_data": False,
                "valid_from": now,
                "valid_to": None,
                "created_at": now,
                "updated_at": now,
                "tag_prefix": None,
                "default_criticality": None,
                "responsible_team_id": None,
                "category_id": UUID(TEST_MEMBER_ID),
                "key": "test_field",
                "label": "Test Field",
                "field_type": "text",
                "is_required": False,
                "rules": {},
                "is_unique": False,
                "is_encrypted": False,
                "position": 0,
                "contact": {},
                "notes": None,
                "tag": "AST-00001",
                "category_name": "Test Category",
                "model": None,
                "manufacturer_id": None,
                "manufacturer_name": None,
                "supplier_id": None,
                "supplier_name": None,
                "serial_number": None,
                "owner_org_unit_id": UUID(TEST_MEMBER_ID),
                "owner_org_unit_name": "Test Org Unit",
                "owner_org_unit_path": "test_path",
                "location_id": None,
                "location_name": None,
                "holder_type": None,
                "holder_id": None,
                "holder_member_id": None,
                "holder_team_id": None,
                "component_id": UUID(TEST_MEMBER_ID),
                "parent_asset_id": UUID(TEST_MEMBER_ID),
                "child_asset_id": UUID(TEST_MEMBER_ID),
                "attached_at": now,
                "detached_at": None,
                "holder_display_name": None,
                "criticality": None,
                "purchase_date": None,
                "purchase_cost": None,
                "warranty_end": None,
                "custom_fields": {},
                "encrypted_fields": {},
                "idempotency_key": None,
                "query": {},
                "sort": "-created_at",
                "columns": [],
            }
        )

    async def fetchval(self, query: str, *args: Any, **kwargs: Any) -> Any:
        q_lower = query.lower()
        if "resolve_organization" in q_lower:
            return UUID(TEST_ORG_ID)
        if "settings" in q_lower:
            return "{}"
        if "organization_modules" in q_lower:
            # `is_module_installed`'s own query selects `status`, not a boolean; the real check is
            # `status == "installed"` (app.modules.organization.modules.is_module_installed).
            return "installed"
        if "is_module_installed" in q_lower or "installed" in q_lower:
            return True
        return 1


class DoubleAcquire:
    def __init__(self, conn: DoubleConn) -> None:
        self.conn = conn

    async def __aenter__(self) -> DoubleConn:
        return self.conn

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        pass


class DoublePool:
    def __init__(self) -> None:
        self.conn = DoubleConn()

    def acquire(self, *, timeout: float | None = None) -> DoubleAcquire:
        return DoubleAcquire(self.conn)

    async def fetchval(self, query: str, *args: Any, **kwargs: Any) -> Any:
        return await self.conn.fetchval(query, *args, **kwargs)

    async def close(self) -> None:
        pass


class DoubleSecrets:
    async def resolve(self, ref: str) -> str:
        return "dummy-secret-value"

    async def get(self, ref: str) -> str:
        return "dummy-secret-value"


class DoubleRegistry:
    def __init__(self, auth: Any) -> None:
        self.auth = auth
        self.secrets = DoubleSecrets()

    async def resolve_secret(self, ref: str) -> str:
        return "dummy-secret-value"

    async def health(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "providers": {
                "auth": {"status": "healthy"},
                "secrets": {"status": "healthy"},
                "telemetry": {"status": "healthy"},
                "events": {"status": "healthy"},
            },
        }


class ExchangeAuth(MockAuthProvider):
    """Mock IdP whose exchanged access token verifies, so the public sign-in route can succeed."""

    async def exchange_code(
        self, code: str, redirect_uri: str, code_verifier: str | None = None
    ) -> dict[str, Any]:
        tokens = self._issue()
        tokens["access_token"] = json.dumps(
            {"sub": "authz-matrix-subject", "organization_id": TEST_ORG_ID, "roles": ["admin"]}
        )
        return tokens


MATRIX_ORIGIN = "http://localhost:5173"


@pytest.fixture
def authz_app() -> FastAPI:
    """Create test application wired with in-memory double providers and pools."""
    ctx = ProviderContext(env="development", pillar="auth", base_dir=Path())
    auth = ExchangeAuth(ctx)
    registry = DoubleRegistry(auth)

    email_cfg = type("EmailCfg", (), {"enabled": False})()
    channels_cfg = type("ChannelsCfg", (), {"email": email_cfg})()
    notifications_cfg = type("NotificationsCfg", (), {"channels": channels_cfg})()
    db_cfg = type(
        "Db",
        (),
        {
            "statement_timeout_ms": 1000,
            "idle_in_transaction_timeout_ms": 1000,
            "behind_pgbouncer": False,
        },
    )()

    config = type(
        "Config",
        (),
        {
            "env": "development",
            "providers": type("Providers", (), {"auth": type("Auth", (), {"type": "mock"})()})(),
            "database": db_cfg,
            "notifications": notifications_cfg,
            "platform": type("Platform", (), {"allowed_origins": [MATRIX_ORIGIN]})(),
        },
    )()

    pool = DoublePool()

    app = create_app(
        bootstrap=Bootstrap(
            load_config=lambda: config,
            build_registry=lambda cfg: registry,
            open_pool=lambda cfg, secret: pool,
            close_pool=lambda p: None,
        )
    )
    app.state.config = config
    app.state.registry = registry
    app.state.pool = pool
    app.state.session_cookie_key = derive_key(secrets.token_hex(16))
    return app


def as_member(role: str, scope: ScopeType = ScopeType.ORGANIZATION) -> MemberContext:
    """Build a MemberContext fixture holding a single grant at the requested scope (§C8.2)."""
    grants = (
        (RoleGrant(id="grant-1", organization_id=TEST_ORG_ID, role_key=role, scope_type=scope),)
        if role != "none"
        else ()
    )
    return MemberContext(
        member_id=TEST_MEMBER_ID,
        organization_id=TEST_ORG_ID,
        is_suspended=False,
        grants=grants,
    )
