// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

// The navigation, declared as data (§C4.9): each item names the permission and/or installed module it
// needs, and the sidebar shows only the items the signed-in member passes. Adding a screen is adding a
// line here and a route in its feature; no layout code changes. Labels are translation keys.
import {
  Bell,
  Boxes,
  LayoutDashboard,
  Network,
  Settings,
  ShieldCheck,
  Tags,
  UserRound,
  Users,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import type { TranslationKey } from "@/lib/i18n";
import { can, hasModule, type Me, type ModuleKey } from "@/lib/permissions";

export interface NavItem {
  to: string;
  labelKey: TranslationKey;
  icon: LucideIcon;
  /** The member must hold this permission (at any scope) to see the item. */
  permission?: string;
  /** The organization must have this module installed to see the item. */
  module?: ModuleKey;
}

export const NAV_ITEMS: readonly NavItem[] = [
  { to: "/", labelKey: "nav.items.dashboard", icon: LayoutDashboard },
  { to: "/organization", labelKey: "nav.items.organization", icon: Network, permission: "org_unit.read" },
  { to: "/teams", labelKey: "nav.items.teams", icon: Users, permission: "team.read" },
  { to: "/members", labelKey: "nav.items.members", icon: UserRound, permission: "member.read" },
  { to: "/assets", labelKey: "nav.items.assets", icon: Boxes, permission: "asset.read", module: "assets" },
  {
    to: "/admin/asset-categories",
    labelKey: "nav.items.asset_categories",
    icon: Tags,
    permission: "asset.update",
    module: "assets",
  },
  {
    to: "/maintenance",
    labelKey: "nav.items.maintenance",
    icon: Wrench,
    permission: "work_order.read",
    module: "maintenance",
  },
  { to: "/notifications", labelKey: "nav.items.notifications", icon: Bell, permission: "notification.read" },
  { to: "/admin", labelKey: "nav.items.admin", icon: ShieldCheck, permission: "role_grant.read" },
  { to: "/settings", labelKey: "nav.items.my_settings", icon: Settings },
];

/** The items `me` may see: those whose permission and module (if any) it satisfies. */
export function visibleItems(items: readonly NavItem[], me: Me | undefined): NavItem[] {
  return items.filter((item) => {
    if (item.permission !== undefined && !can(me, item.permission)) return false;
    if (item.module !== undefined && !hasModule(me, item.module)) return false;
    return true;
  });
}
