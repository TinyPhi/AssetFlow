# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

Raw SQL only (D6): op.execute(...). Every new table needs organization_id, ENABLE and FORCE ROW LEVEL
SECURITY, four organization policies and an organization_id index; scripts/check-migrations.py checks.
Name schema objects with their schema (public.<table>) and write a full downgrade().
"""

from collections.abc import Sequence

from alembic import op

revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else 'raise NotImplementedError("write the upgrade SQL")'}


def downgrade() -> None:
    ${downgrades if downgrades else 'raise NotImplementedError("write the downgrade SQL")'}
