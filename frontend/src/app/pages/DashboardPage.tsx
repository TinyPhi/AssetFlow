// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type React from "react";
import { HealthStatus } from "@/app/HealthStatus";
import { Skeleton } from "@/components/ui";
import { t } from "@/lib/i18n";
import { useMe } from "@/lib/permissions";

/** The landing page. P7-04b adds the real dashboard shell; for now: who you are and platform health. */
export const DashboardPage: React.FC = () => {
  const { data: me, isPending } = useMe();
  return (
    <section className="space-y-4">
      <h1 className="text-2xl font-bold">{t("pages.dashboard.title")}</h1>
      {isPending ? (
        <Skeleton rows={1} />
      ) : (
        <p className="text-muted">
          {t("pages.dashboard.welcome")}
          {me?.display_name ? `, ${me.display_name}` : ""}
        </p>
      )}
      <HealthStatus />
    </section>
  );
};
