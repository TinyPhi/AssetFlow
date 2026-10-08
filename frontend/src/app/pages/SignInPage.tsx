// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type React from "react";
import { HealthStatus } from "@/app/HealthStatus";
import { t } from "@/lib/i18n";

/** Placeholder until P7-02b builds sign-in; it keeps the public platform health visible. */
export const SignInPage: React.FC = () => (
  <main className="mx-auto flex min-h-screen max-w-lg flex-col justify-center gap-4 bg-background p-6 text-foreground">
    <h1 className="text-2xl font-bold">{t("pages.sign_in.title")}</h1>
    <p className="text-sm text-muted">{t("pages.sign_in.pending")}</p>
    <HealthStatus />
  </main>
);
