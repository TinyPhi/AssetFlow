# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Support for the organization settings API (§B10, M1.4-T9).

Revision ID: 0008_org_settings_support
Revises: 0007_org_create_support
Create Date: 2026-10-03 00:00:08.000000

`organizations` had SELECT and (since 0007) INSERT for `assetflow_api`, but no UPDATE: nothing
wrote to an existing organization row before this plan. The fail-closed `organizations_update`
policy (`id = app.organization_id`) is what actually authorizes a row, same as the INSERT grant
added in 0007; this grant only lifts the privilege check.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008_org_settings_support"
down_revision: str | None = "0007_org_create_support"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("GRANT UPDATE ON public.organizations TO assetflow_api")


def downgrade() -> None:
    op.execute("REVOKE UPDATE ON public.organizations FROM assetflow_api")
