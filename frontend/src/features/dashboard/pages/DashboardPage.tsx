// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import {
  Bell,
  Boxes,
  Network,
  Settings,
  ShieldCheck,
  UserRound,
  Users,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import type React from "react";
import { Link } from "react-router";
import { t, type TranslationKey } from "@/lib/i18n";
import { can, hasModule, useMe, type ModuleKey } from "@/lib/permissions";

interface DashboardTile {
  titleKey: TranslationKey;
  to: string;
  icon: LucideIcon;
  permission?: string;
  module?: ModuleKey;
}

const TILES: DashboardTile[] = [
  { titleKey: "nav.items.organization", to: "/organization", icon: Network, permission: "org_unit.read" },
  { titleKey: "nav.items.teams", to: "/teams", icon: Users, permission: "team.read" },
  { titleKey: "nav.items.members", to: "/members", icon: UserRound, permission: "member.read" },
  { titleKey: "nav.items.assets", to: "/assets", icon: Boxes, permission: "asset.read", module: "assets" },
  {
    titleKey: "nav.items.maintenance",
    to: "/maintenance",
    icon: Wrench,
    permission: "work_order.read",
    module: "maintenance",
  },
  { titleKey: "nav.items.notifications", to: "/notifications", icon: Bell, permission: "notification.read" },
  { titleKey: "nav.items.admin", to: "/admin", icon: ShieldCheck, permission: "role_grant.read" },
  { titleKey: "nav.items.my_settings", to: "/settings", icon: Settings },
];

export const DashboardPage: React.FC = () => {
  const { data: me } = useMe();
  const displayName = me?.display_name || "Member";
  const orgName = me?.organization.name || "AssetFlow";

  const availableTiles = TILES.filter((tile) => {
    if (tile.permission && !can(me, tile.permission)) return false;
    if (tile.module && !hasModule(me, tile.module)) return false;
    return true;
  });

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-1 border-b border-border pb-5">
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">
          {t("pages.dashboard.welcome")}
          {", "}
          {displayName}
        </h1>
        <p className="text-sm text-muted">
          {orgName}
          {" • "}
          {t("app.shell.title")}
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {availableTiles.map((tile) => (
          <Link
            key={tile.to}
            to={tile.to}
            className="group flex flex-col justify-between rounded-xl border border-border bg-surface p-5 transition-all hover:border-primary hover:shadow-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus"
          >
            <div className="flex items-center gap-3.5">
              <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-primary/10 text-primary transition-colors group-hover:bg-primary group-hover:text-primary-foreground">
                <tile.icon className="h-6 w-6" aria-hidden="true" />
              </div>
              <h2 className="text-base font-semibold text-foreground group-hover:text-primary">
                {t(tile.titleKey)}
              </h2>
            </div>
            <div className="mt-4 flex items-center justify-between text-xs text-muted">
              <span>{t("app.shell.title")}</span>
              <span className="font-medium text-primary">{"→"}</span>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
};
