// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { Activity, Menu, Wifi, WifiOff, X } from "lucide-react";
import React, { useEffect, useRef, useState } from "react";
import { Outlet } from "react-router";
import { useToast } from "@/app/toastContext";
import { useOnlineStatus } from "@/app/useOnlineStatus";
import { NotificationBell } from "@/features/notifications/components/NotificationBell";
import { t } from "@/lib/i18n";
import { Sidebar } from "./Sidebar";
import { ThemeToggle } from "./ThemeToggle";

/** Raises a toast whenever the network status changes (never on first render). */
function useNetworkToast(isOnline: boolean): void {
  const { showToast } = useToast();
  const previous = useRef(isOnline);

  useEffect(() => {
    if (previous.current === isOnline) return;
    previous.current = isOnline;
    if (isOnline) {
      showToast(t("app.toast.network_online"), "success");
    } else {
      showToast(t("app.toast.network_offline"), "danger");
    }
  }, [isOnline, showToast]);
}

/**
 * The signed-in layout: header, navigation and the page. From `md` up the navigation is a sidebar; on
 * a narrow screen it collapses behind a menu button. Nothing here has a fixed width, so there is no
 * sideways scroll from 320 px to 2560 px (§B10).
 */
export const Layout: React.FC = () => {
  const isOnline = useOnlineStatus();
  useNetworkToast(isOnline);
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:rounded focus:bg-surface focus:p-2"
      >
        {t("nav.menu.skip_to_content")}
      </a>
      <header className="flex items-center justify-between gap-3 border-b border-border bg-surface px-4 py-2 md:px-6">
        <div className="flex min-w-0 items-center gap-3">
          <button
            type="button"
            className="flex h-11 w-11 items-center justify-center rounded-lg hover:bg-border focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus md:hidden"
            aria-expanded={menuOpen}
            aria-controls="primary-navigation"
            aria-label={menuOpen ? t("nav.menu.close") : t("nav.menu.open")}
            onClick={() => {
              setMenuOpen((open) => !open);
            }}
          >
            {menuOpen ? (
              <X aria-hidden="true" className="h-5 w-5" />
            ) : (
              <Menu aria-hidden="true" className="h-5 w-5" />
            )}
          </button>
          <Activity aria-hidden="true" className="h-6 w-6 shrink-0 text-primary" />
          <span className="truncate text-lg font-bold tracking-tight">{t("app.shell.title")}</span>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <div
            role="status"
            className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs ${
              isOnline
                ? "border-success bg-success-surface text-success"
                : "border-danger bg-surface text-danger"
            }`}
          >
            {isOnline ? (
              <>
                <Wifi aria-hidden="true" className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">{t("app.shell.online")}</span>
              </>
            ) : (
              <>
                <WifiOff aria-hidden="true" className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">{t("app.shell.offline")}</span>
              </>
            )}
          </div>
          <NotificationBell />
          <ThemeToggle />
        </div>
      </header>

      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <div
          id="primary-navigation"
          className={`border-b border-border bg-surface p-3 md:block md:w-60 md:shrink-0 md:border-b-0 md:border-r ${
            menuOpen ? "block" : "hidden"
          }`}
        >
          <Sidebar
            onNavigate={() => {
              setMenuOpen(false);
            }}
          />
        </div>
        <main id="main" className="min-w-0 flex-1 p-4 md:p-6">
          <Outlet />
        </main>
      </div>

      <footer className="border-t border-border px-6 py-4 text-center text-xs text-muted">
        {t("app.shell.footer")}
      </footer>
    </div>
  );
};
