// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

// The shape of `GET /api/v1/me` (backend/app/modules/organization/profile.py).

export type ScopeType = "organization" | "org_unit" | "team" | "self";

export interface PermissionScope {
  scope_type: ScopeType;
  scope_id: string | null;
}

export interface GrantedPermission {
  permission: string;
  scopes: PermissionScope[];
}

export type ModuleKey = "assets" | "maintenance";

export interface Me {
  member_id: string;
  display_name: string;
  locale: string;
  organization: { id: string; name: string; timezone: string };
  is_suspended: boolean;
  permissions: GrantedPermission[];
  installed_modules: ModuleKey[];
}

/** What a record looks like to the client-side scope hint (see `usePermission`). */
export interface ScopedRecord {
  orgUnitId?: string;
  teamId?: string;
  holderMemberId?: string;
}
