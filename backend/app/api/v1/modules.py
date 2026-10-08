# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Organization modules management endpoints (§B5.9, M1.6-T4)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_db, permission_extra, require_member
from app.core.scope import MemberContext
from app.modules.assets.catalog.service import seed_assets_catalog
from app.modules.organization.modules import (
    MODULE_DEPENDENCIES,
    MODULE_KEYS,
    ModuleKey,
    install_module,
    is_module_installed,
    uninstall_module,
)

router = APIRouter(prefix="/modules", tags=["Modules"])


class ModuleInfo(BaseModel):
    key: str
    is_installed: bool
    dependencies: list[str]


class InstallModuleResponse(BaseModel):
    module_id: str
    status: str


class UninstallModuleResponse(BaseModel):
    module_key: str
    status: str


@router.get("", response_model=list[ModuleInfo], openapi_extra=permission_extra("role_grant.read"))
async def list_modules(
    member_ctx: MemberContext = Depends(require_member("role_grant.read")),
    conn: Any = Depends(get_db),
) -> list[ModuleInfo]:
    org_id = UUID(member_ctx.organization_id)
    result: list[ModuleInfo] = []
    for key in MODULE_KEYS:
        installed = await is_module_installed(conn, org_id, key)
        deps = list(MODULE_DEPENDENCIES.get(key, ()))
        result.append(ModuleInfo(key=key, is_installed=installed, dependencies=deps))
    return result


@router.post(
    "/{module_key}/install",
    response_model=InstallModuleResponse,
    openapi_extra=permission_extra("module.manage"),
)
async def install_org_module(
    module_key: ModuleKey,
    member_ctx: MemberContext = Depends(require_member("module.manage")),
    conn: Any = Depends(get_db),
) -> InstallModuleResponse:
    org_id = UUID(member_ctx.organization_id)
    actor_id = UUID(member_ctx.member_id) if member_ctx.member_id else None
    mod_id = await install_module(conn, org_id, module_key, installed_by=actor_id)
    if module_key == "assets":
        # Seed the organization's categories and custom fields from its domain template
        # (§B5.9, §B7.1, P8-06); idempotent, same transaction as the install above.
        domain_key = await conn.fetchval("SELECT domain_key FROM public.organizations WHERE id = $1", org_id)
        if domain_key:
            await seed_assets_catalog(
                conn, organization_id=org_id, domain_key=domain_key, actor_member_id=actor_id
            )
    return InstallModuleResponse(module_id=str(mod_id), status="installed")


@router.post(
    "/{module_key}/uninstall",
    response_model=UninstallModuleResponse,
    openapi_extra=permission_extra("module.manage"),
)
async def uninstall_org_module(
    module_key: ModuleKey,
    member_ctx: MemberContext = Depends(require_member("module.manage")),
    conn: Any = Depends(get_db),
) -> UninstallModuleResponse:
    org_id = UUID(member_ctx.organization_id)
    actor_id = UUID(member_ctx.member_id) if member_ctx.member_id else None
    await uninstall_module(conn, org_id, module_key, uninstalled_by=actor_id)
    return UninstallModuleResponse(module_key=module_key, status="uninstalled")
