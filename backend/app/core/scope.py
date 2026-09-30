# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Scope resolution engine (§B5.3, §C4.4, M1.3-T5).

Evaluates a member's effective role grants against target resources and builds
the ScopeFilter for list queries.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.core.permissions import (
    ROLE_PERMISSIONS,
    ScopeFilter,
    ScopeType,
    matches_permission,
)
from app.core.problems import PermissionDeniedError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RoleGrant:
    """A role granted to a member at a specific scope (§B5.2, §B5.3)."""

    id: str
    organization_id: str
    role_key: str
    scope_type: ScopeType
    scope_id: str | None = None
    org_unit_path: str | None = None
    source: str = "idp"
    expires_at: datetime | None = None

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now(UTC) >= self.expires_at

    def grants_permission(self, required_permission: str) -> bool:
        """Check if this role grant provides the required permission."""
        if self.is_expired:
            return False
        perms = ROLE_PERMISSIONS.get(self.role_key, frozenset())
        return any(matches_permission(p, required_permission) for p in perms)


@dataclass(frozen=True)
class MemberContext:
    """Current authenticated member security context."""

    member_id: str
    organization_id: str
    is_suspended: bool = False
    grants: tuple[RoleGrant, ...] = ()
    team_ids: tuple[str, ...] = ()
    primary_org_unit_path: str | None = None


def _grant_covers_resource(
    grant: RoleGrant,
    member: MemberContext,
    resource: dict[str, Any],
) -> bool:
    if grant.scope_type == ScopeType.ORGANIZATION:
        return True
    owner_path = resource.get("owner_org_unit_path") or resource.get("org_unit_path")
    if grant.scope_type == ScopeType.ORG_UNIT and grant.org_unit_path and owner_path:
        return bool(owner_path == grant.org_unit_path or owner_path.startswith(f"{grant.org_unit_path}."))
    team_id = resource.get("team_id")
    if grant.scope_type == ScopeType.TEAM:
        if grant.scope_id and team_id and grant.scope_id == team_id:
            return True
        if team_id and team_id in member.team_ids:
            return True
    holder_id = resource.get("holder_member_id") or resource.get("holder_id")
    assignee_id = resource.get("assignee_member_id") or resource.get("assignee_id")
    return bool(grant.scope_type == ScopeType.SELF and member.member_id in (holder_id, assignee_id))


class ScopeResolver:
    """Evaluates scoped permissions and generates list filters (§B5.3)."""

    def __init__(self, role_permissions: dict[str, frozenset[str]] | None = None) -> None:
        self.role_permissions = role_permissions or ROLE_PERMISSIONS

    def get_effective_grants_for_permission(self, member: MemberContext, permission: str) -> list[RoleGrant]:
        """Return all active grants that grant the requested permission."""
        if member.is_suspended:
            return []
        effective: list[RoleGrant] = []
        for grant in member.grants:
            if grant.grants_permission(permission):
                effective.append(grant)
        return effective

    def has_permission(self, member: MemberContext, permission: str) -> bool:
        """Return True if member has any valid grant satisfying permission."""
        if member.is_suspended:
            return False
        return len(self.get_effective_grants_for_permission(member, permission)) > 0

    def check_access(
        self,
        member: MemberContext,
        permission: str,
        resource: dict[str, Any] | None = None,
    ) -> bool:
        """Check whether member has access to a specific resource under `permission` (§B5.3).

        If `resource` is None, checks only if the member holds the permission at any scope.
        """
        if member.is_suspended:
            return False

        matching_grants = self.get_effective_grants_for_permission(member, permission)
        if not matching_grants:
            return False

        if resource is None:
            return True

        return any(_grant_covers_resource(grant, member, resource) for grant in matching_grants)

    def resolve_scope_filter(self, member: MemberContext, permission: str) -> ScopeFilter:
        """Build the ScopeFilter for list queries (§B5.3).

        Organization scope skips granular filters.
        Otherwise unions org unit paths, team ids, and self (member_id).
        """
        if member.is_suspended:
            return ScopeFilter()

        matching_grants = self.get_effective_grants_for_permission(member, permission)
        if not matching_grants:
            return ScopeFilter()

        # Check if any grant is organization-wide
        for grant in matching_grants:
            if grant.scope_type == ScopeType.ORGANIZATION:
                return ScopeFilter.all_organization()

        org_paths: set[str] = set()
        team_ids: set[str] = set(member.team_ids)
        includes_self = False

        for grant in matching_grants:
            if grant.scope_type == ScopeType.ORG_UNIT and grant.org_unit_path:
                org_paths.add(grant.org_unit_path)
            elif grant.scope_type == ScopeType.TEAM:
                if grant.scope_id:
                    team_ids.add(grant.scope_id)
            elif grant.scope_type == ScopeType.SELF:
                includes_self = True

        return ScopeFilter(
            organization=False,
            org_unit_paths=tuple(sorted(org_paths)),
            team_ids=tuple(sorted(team_ids)),
            member_id=member.member_id if includes_self else None,
        )

    def require(
        self,
        member: MemberContext,
        permission: str,
        resource: dict[str, Any] | None = None,
    ) -> None:
        """Enforce permission check; raise PermissionDeniedError on refusal."""
        if not self.check_access(member, permission, resource):
            raise PermissionDeniedError(f"Permission {permission!r} denied for the requested resource scope.")


# Default singleton instance
default_scope_resolver = ScopeResolver()
