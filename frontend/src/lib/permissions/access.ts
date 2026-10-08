// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

// Pure permission checks over a `Me`. UI hiding is a convenience only: the API decides every request
// (§C4.9), so a mistake here can show a button that then answers 403, never grant anything.
import type { Me, ModuleKey, PermissionScope, ScopedRecord } from "./types";

function scopeCovers(scope: PermissionScope, me: Me, record: ScopedRecord): boolean {
  switch (scope.scope_type) {
    case "organization":
      return true;
    case "org_unit":
      return record.orgUnitId !== undefined && scope.scope_id === record.orgUnitId;
    case "team":
      return record.teamId !== undefined && scope.scope_id === record.teamId;
    case "self":
      return record.holderMemberId !== undefined && record.holderMemberId === me.member_id;
  }
}

/**
 * True when `me` holds `permission`; with a `record`, only when one of the scopes it applies at covers
 * that record (an org-unit scope is matched by the unit's id only, a hint: the server also covers the
 * unit's descendants).
 */
export function can(me: Me | undefined, permission: string, record?: ScopedRecord): boolean {
  if (me === undefined || me.is_suspended) return false;
  const granted = me.permissions.find((p) => p.permission === permission);
  if (granted === undefined) return false;
  if (record === undefined) return true;
  return granted.scopes.some((scope) => scopeCovers(scope, me, record));
}

export function hasModule(me: Me | undefined, module: ModuleKey): boolean {
  return me?.installed_modules.includes(module) ?? false;
}
