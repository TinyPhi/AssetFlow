// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type React from "react";
import { NavLink } from "react-router";
import { t } from "@/lib/i18n";
import { useMe } from "@/lib/permissions";
import { NAV_ITEMS, visibleItems } from "./navConfig";

interface SidebarProps {
  /** Called when a link is followed (the narrow-screen menu closes itself). */
  onNavigate?: () => void;
}

/** The navigation list. Touch targets are at least 44 px high (§B10). */
export const Sidebar: React.FC<SidebarProps> = ({ onNavigate }) => {
  const { data: me } = useMe();
  const items = visibleItems(NAV_ITEMS, me);
  return (
    <nav aria-label={t("nav.label")}>
      <ul className="space-y-1">
        {items.map((item) => (
          <li key={item.to}>
            <NavLink
              to={item.to}
              end={item.to === "/"}
              onClick={onNavigate}
              className={({ isActive }) =>
                `flex min-h-11 items-center gap-3 rounded-lg px-3 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus ${
                  isActive ? "bg-primary text-primary-foreground" : "text-foreground hover:bg-border"
                }`
              }
            >
              <item.icon aria-hidden="true" className="h-5 w-5 shrink-0" />
              <span className="min-w-0 truncate">{t(item.labelKey)}</span>
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
};
