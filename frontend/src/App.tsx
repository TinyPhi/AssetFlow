// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Activity, ShieldCheck } from "lucide-react";
import type React from "react";
import { t } from "@/lib/i18n";

const queryClient = new QueryClient();

export const AppContent: React.FC = () => {
  return (
    <main className="min-h-screen flex items-center justify-center p-6 bg-background">
      <div className="max-w-md w-full bg-surface rounded-xl shadow-md p-8 border border-border">
        <div className="flex items-center gap-3 mb-4">
          <Activity aria-hidden="true" className="h-8 w-8 text-primary" />
          <h1 className="text-2xl font-bold tracking-tight text-foreground">{t("app.shell.title")}</h1>
        </div>
        <p className="text-muted mb-6">{t("app.shell.tagline")}</p>
        <div
          role="status"
          className="flex items-center gap-2 text-sm text-success bg-success-surface p-3 rounded-lg border border-success"
        >
          <ShieldCheck aria-hidden="true" className="h-5 w-5 flex-shrink-0" />
          <span>{t("app.shell.status_ready")}</span>
        </div>
      </div>
    </main>
  );
};

export const App: React.FC = () => {
  return (
    <QueryClientProvider client={queryClient}>
      <AppContent />
    </QueryClientProvider>
  );
};

export default App;
