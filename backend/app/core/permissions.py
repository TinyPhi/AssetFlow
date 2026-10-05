# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Permissions and ScopeFilter definitions (§B5.3, §C1.6, M1.3-T5).

Declares permissions using the `<entity>.<action>` format (with `*` wildcard permitted only
at the end of a segment) and platform permissions using `platform.<action>`.
Defines default roles and the `ScopeFilter` dataclass used by repository list queries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class ScopeType(StrEnum):
    """Scope granularity from narrow to wide (§B5.3)."""

    SELF = "self"
    TEAM = "team"
    ORG_UNIT = "org_unit"
    ORGANIZATION = "organization"


# Pattern: <entity>.<action> or platform.<action>, with wildcard '*' allowed only at the end
_PERMISSION_RE = re.compile(r"^[a-z][a-z0-9_]*\.([a-z0-9_]+|\*)$")


def validate_permission_pattern(perm: str) -> bool:
    """Return True if `perm` is a valid permission identifier (§C1.6)."""
    return bool(_PERMISSION_RE.match(perm))


def matches_permission(granted: str, required: str) -> bool:
    """Return True if the granted permission satisfies the required permission.

    Wildcard '*' is supported only at the end (e.g. `work_order.*` satisfies `work_order.dispatch`,
    and `*` satisfies any organization permission).
    Platform permissions (starting with `platform.`) are never matched by non-platform wildcards.
    """
    if granted == "*":
        return not required.startswith("platform.")
    if granted == required:
        return True
    if granted.endswith(".*"):
        prefix = granted[:-1]  # keep the trailing dot
        return required.startswith(prefix)
    return False


@dataclass(frozen=True)
class ScopeFilter:
    """Filters list queries by the member's effective grants (§B5.3).

    Repository list methods take a ScopeFilter to constrain query results to records
    covered by the member's scope.
    """

    organization: bool = False
    org_unit_paths: tuple[str, ...] = ()
    team_ids: tuple[str, ...] = ()
    member_id: str | None = None

    @classmethod
    def all_organization(cls) -> ScopeFilter:
        """Create an unrestricted organization-level scope filter."""
        return cls(organization=True)

    @property
    def is_empty(self) -> bool:
        """Return True if the filter permits no records at all."""
        return (
            not self.organization and not self.org_unit_paths and not self.team_ids and self.member_id is None
        )

    def covers(
        self,
        *,
        owner_org_unit_path: str | None = None,
        team_id: str | None = None,
        holder_id: str | None = None,
        assignee_id: str | None = None,
    ) -> bool:
        """Check whether a specific resource falls within this scope filter."""
        if self.organization:
            return True
        if self.member_id is not None:
            if holder_id is not None and holder_id == self.member_id:
                return True
            if assignee_id is not None and assignee_id == self.member_id:
                return True
        if team_id is not None and team_id in self.team_ids:
            return True
        if owner_org_unit_path is not None:
            for allowed_path in self.org_unit_paths:
                # ltree hierarchical subpath match: exact match or child prefix with '.'
                if owner_org_unit_path == allowed_path or owner_org_unit_path.startswith(f"{allowed_path}."):
                    return True
        return False


#: Standard default permissions
DEFAULT_PERMISSIONS: frozenset[str] = frozenset(
    {
        # Platform
        "platform.organization_create",
        "platform.resolve_organization",
        "platform.admin",
        # Organization admin & access
        "role_grant.manage",
        "role_grant.read",
        "org_unit.create",
        "org_unit.update",
        "org_unit.archive",
        "org_unit.read",
        "location.create",
        "location.update",
        "location.archive",
        "location.delete",
        "location.read",
        "team.create",
        "team.update",
        "team.archive",
        "team.read",
        "member.invite",
        "member.update",
        "member.read",
        "module.manage",
        "module.read",
        "organization.manage",
        # Assets
        "asset.create",
        "asset.read",
        "asset.update",
        "asset.retire",
        "asset.assign",
        "asset.return",
        "asset.acknowledge",
        "asset.read_sensitive",
        "qr.generate",
        "qr.read",
        # Maintenance
        "work_request.create",
        "work_request.triage",
        "work_request.read",
        "work_order.create",
        "work_order.dispatch",
        "work_order.execute",
        "work_order.read",
        "maintenance.plan.manage",
        "maintenance.plan.read",
        "maintenance.schedule.manage",
        "maintenance.schedule.read",
        # Audit and Notifications
        "audit.read",
        "report.export",
        "notification.read",
        "notification.manage",
        "notification_channel.read",
        "notification_channel.manage",
        "notification_delivery.read",
        "notification_preference.manage",
    }
)

#: Default role-to-permissions mapping
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "admin": frozenset({"*"}),
    "asset_manager": frozenset(
        {
            "asset.*",
            "qr.*",
            "location.*",
            "audit.read",
            "report.export",
            "org_unit.read",
            "location.read",
            "team.read",
            "member.read",
        }
    ),
    "planner": frozenset(
        {
            "maintenance.plan.*",
            "maintenance.schedule.*",
            "work_order.create",
            "work_order.dispatch",
            "work_request.triage",
            "work_request.read",
            "work_order.read",
            "asset.read",
            "location.read",
            "team.read",
            "member.read",
        }
    ),
    "team_lead": frozenset(
        {
            "work_order.*",
            "work_request.triage",
            "work_request.read",
            "location.read",
            "team.read",
            "member.read",
            "asset.read",
        }
    ),
    "technician": frozenset(
        {
            "work_order.execute",
            "work_order.read",
            "work_request.read",
            "location.read",
            "asset.read",
            "team.read",
        }
    ),
    "member": frozenset(
        {
            "asset.read",
            "asset.acknowledge",
            "location.read",
            "work_request.create",
            "work_request.read",
            "notification.read",
            "notification_preference.manage",
        }
    ),
}
