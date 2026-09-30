// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { AlertCircle, CheckCircle2, RefreshCw, Server } from "lucide-react";
import React from "react";
import { isHealthy, usePlatformHealth } from "@/app/usePlatformHealth";
import { t } from "@/lib/i18n";

export const HealthStatus: React.FC = () => {
  const health = usePlatformHealth();
  const { isLoading, isFetching, isError, refetch } = health;
  const healthy = isHealthy(health);

  return (
    <section
      aria-labelledby="health-status-title"
      className="bg-surface rounded-xl border border-border p-5 shadow-sm mt-6"
    >
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Server aria-hidden="true" className="h-5 w-5 text-primary" />
          <h2 id="health-status-title" className="text-base font-semibold text-foreground">
            {t("app.shell.health_title")}
          </h2>
        </div>
        <button
          type="button"
          onClick={() => {
            void refetch();
          }}
          disabled={isFetching}
          aria-label={t("app.shell.health_refresh")}
          title={t("app.shell.health_refresh")}
          className="p-1.5 rounded-lg border border-border text-muted hover:text-foreground transition-colors disabled:opacity-50"
        >
          <RefreshCw aria-hidden="true" className={`h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />
        </button>
      </div>

      {isLoading && (
        <div role="status" className="text-sm text-muted animate-pulse py-2">
          {t("app.shell.health_checking")}
        </div>
      )}

      {!isLoading && healthy && (
        <div
          role="status"
          className="flex items-center gap-2 text-sm p-2.5 rounded-lg border text-success bg-success-surface border-success"
        >
          <CheckCircle2 aria-hidden="true" className="h-4 w-4 flex-shrink-0" />
          <span className="font-medium">{t("app.shell.health_ok")}</span>
        </div>
      )}

      {!isLoading && !healthy && (
        <div
          role="alert"
          className="flex items-center gap-2 text-sm text-danger bg-surface p-3 rounded-lg border border-danger"
        >
          <AlertCircle aria-hidden="true" className="h-4 w-4 flex-shrink-0" />
          <span>{isError ? t("app.shell.health_error") : t("app.shell.health_unhealthy")}</span>
        </div>
      )}
    </section>
  );
};
