// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { Activity, AlertCircle, ShieldCheck, Wifi, WifiOff } from "lucide-react";
import React, { useEffect, useRef } from "react";
import { HealthStatus } from "@/app/HealthStatus";
import { useToast } from "@/app/toastContext";
import { useOnlineStatus } from "@/app/useOnlineStatus";
import { isHealthy, usePlatformHealth } from "@/app/usePlatformHealth";
import { t } from "@/lib/i18n";

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

export const AppShell: React.FC = () => {
  const isOnline = useOnlineStatus();
  useNetworkToast(isOnline);
  const ready = isHealthy(usePlatformHealth());

  return (
    <div className="min-h-screen flex flex-col bg-background text-foreground">
      <header className="border-b border-border bg-surface px-6 py-3.5 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Activity aria-hidden="true" className="h-6 w-6 text-primary" />
          <span className="font-bold tracking-tight text-lg">{t("app.shell.title")}</span>
        </div>
        <div className="flex items-center gap-3">
          <div
            role="status"
            className={`flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border ${
              isOnline
                ? "bg-success-surface border-success text-success"
                : "bg-surface border-danger text-danger"
            }`}
          >
            {isOnline ? (
              <>
                <Wifi aria-hidden="true" className="h-3.5 w-3.5" />
                <span>{t("app.shell.online")}</span>
              </>
            ) : (
              <>
                <WifiOff aria-hidden="true" className="h-3.5 w-3.5" />
                <span>{t("app.shell.offline")}</span>
              </>
            )}
          </div>
        </div>
      </header>

      <main className="flex-1 flex items-center justify-center p-6">
        <div className="max-w-lg w-full">
          <div className="bg-surface rounded-xl shadow-md p-8 border border-border">
            <div className="flex items-center gap-3 mb-3">
              <Activity aria-hidden="true" className="h-8 w-8 text-primary" />
              <h1 className="text-2xl font-bold tracking-tight text-foreground">{t("app.shell.title")}</h1>
            </div>
            <p className="text-muted mb-6 text-sm leading-relaxed">{t("app.shell.tagline")}</p>
            {ready ? (
              <div
                role="status"
                className="flex items-center gap-2 text-sm text-success bg-success-surface p-3 rounded-lg border border-success mb-2"
              >
                <ShieldCheck aria-hidden="true" className="h-5 w-5 flex-shrink-0" />
                <span>{t("app.shell.status_ready")}</span>
              </div>
            ) : (
              <div
                role="status"
                className="flex items-center gap-2 text-sm text-muted bg-surface p-3 rounded-lg border border-border mb-2"
              >
                <AlertCircle aria-hidden="true" className="h-5 w-5 flex-shrink-0" />
                <span>{t("app.shell.status_not_ready")}</span>
              </div>
            )}

            <HealthStatus />
          </div>
        </div>
      </main>

      <footer className="border-t border-border py-4 px-6 text-center text-xs text-muted">
        {t("app.shell.footer")}
      </footer>
    </div>
  );
};
