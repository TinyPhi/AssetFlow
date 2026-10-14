# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Visit every active organization, one short transaction each (§B9.3).

Used by housekeeping and by any future worker job that must touch every tenant rather than react
to one outbox event. A failure in one organization is logged and does not stop the sweep.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

from app.core.db import Connection, Pool, platform_transaction, worker_context

logger = logging.getLogger(__name__)

SweepFn = Callable[[Connection, UUID], Awaitable[None]]


async def active_organization_ids(pool: Pool) -> list[UUID]:
    """Every active organization's id (the one cross-organization read a worker may make)."""
    async with platform_transaction(pool) as conn:
        rows = await conn.fetch("SELECT * FROM platform.list_active_organizations()")
    return [row[0] for row in rows]


async def for_each_active_organization(pool: Pool, fn: SweepFn) -> None:
    """Run `fn(conn, organization_id)` for every active organization, each in its own transaction."""
    organization_ids = await active_organization_ids(pool)
    for organization_id in organization_ids:
        try:
            async with worker_context(pool, organization_id) as org_conn:
                await fn(org_conn, organization_id)
        except Exception as exc:  # noqa: BLE001 - one organization's failure must not stop the sweep
            logger.warning(
                "worker.sweep.failed",
                extra={"organization_id": str(organization_id), "error_code": type(exc).__name__},
            )
