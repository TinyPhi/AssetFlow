# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Permission constants for the asset API (§B7.1, §C1.6, M2.1-T5, P8-07).

Kept as a small, separate file (per the plan's own file list) so the router and service agree on
one name for each permission rather than repeating the string literal. The permissions themselves
are declared in `app.core.permissions.DEFAULT_PERMISSIONS`.
"""

from __future__ import annotations

__all__ = [
    "CREATE_PERMISSION",
    "READ_PERMISSION",
    "UPDATE_PERMISSION",
]

#: Creating an asset (record-level check against the target owner_org_unit_id, §B5.3).
CREATE_PERMISSION = "asset.create"

#: Reading (detail/list): any scope, including `self` (a member sees the assets they hold).
READ_PERMISSION = "asset.read"

#: Editing an asset's fields (not status, holder or tag - those belong to other plans).
UPDATE_PERMISSION = "asset.update"
