// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { Boxes, CheckCircle2, Download, Trash2, Wrench } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import type React from "react";
import { useEffect, useState } from "react";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui";
import { ProblemError, apiFetch, queryKeys } from "@/lib/api";
import { can, useMe } from "@/lib/permissions";

interface ModuleData {
  key: string;
  is_installed: boolean;
  dependencies: string[];
}

export const ModulesPage: React.FC = () => {
  const { data: me } = useMe();
  const canManage = can(me, "module.manage") || can(me, "organization.manage");
  const [modules, setModules] = useState<ModuleData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const loadModules = () => {
    setLoading(true);
    setError(null);
    apiFetch<ModuleData[]>("/modules")
      .then((list) => {
        setModules(list);
      })
      .catch(() => {
        setError("Failed to load modules");
      })
      .finally(() => {
        setLoading(false);
      });
  };

  useEffect(() => {
    loadModules();
  }, []);

  const handleToggle = async (mod: ModuleData) => {
    const action = mod.is_installed ? "uninstall" : "install";
    setActionError(null);
    try {
      await apiFetch(`/modules/${mod.key}/${action}`, { method: "POST" });
      // Navigation and module guards read the installed modules from /me.
      await queryClient.invalidateQueries({ queryKey: queryKeys.me() });
      loadModules();
    } catch (err: unknown) {
      setActionError(err instanceof ProblemError && err.detail ? err.detail : `Failed to ${action} module`);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-4 border-b border-border pb-5 sm:flex-row sm:items-center">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{"Organization Modules"}</h1>
          <p className="text-sm text-muted">{"Install and manage modular platform extensions"}</p>
        </div>
      </div>

      {actionError && <ErrorState message={actionError} />}

      {loading ? (
        <Skeleton rows={2} />
      ) : error ? (
        <ErrorState message={error} onRetry={loadModules} />
      ) : modules.length === 0 ? (
        <EmptyState title="No modules available" />
      ) : (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
          {modules.map((mod) => (
            <div
              key={mod.key}
              className="flex flex-col justify-between rounded-xl border border-border bg-surface p-6 shadow-sm"
            >
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10 text-primary">
                      {mod.key === "assets" ? <Boxes className="h-6 w-6" /> : <Wrench className="h-6 w-6" />}
                    </div>
                    <div>
                      <h2 className="text-lg font-semibold capitalize text-foreground">{mod.key}</h2>
                      {mod.dependencies.length > 0 && (
                        <p className="text-xs text-muted">{`Requires: ${mod.dependencies.join(", ")}`}</p>
                      )}
                    </div>
                  </div>

                  <span
                    className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium ${
                      mod.is_installed
                        ? "border border-success bg-success-surface text-success"
                        : "border border-border bg-surface text-muted"
                    }`}
                  >
                    {mod.is_installed && <CheckCircle2 className="h-3.5 w-3.5" />}
                    <span>{mod.is_installed ? "Installed" : "Available"}</span>
                  </span>
                </div>
              </div>

              {canManage && (
                <div className="mt-6 border-t border-border pt-4">
                  <button
                    type="button"
                    onClick={() => {
                      void handleToggle(mod);
                    }}
                    className={`flex min-h-11 w-full items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold transition-opacity focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus ${
                      mod.is_installed
                        ? "border border-danger/30 text-danger hover:bg-danger/10"
                        : "bg-primary text-primary-foreground hover:opacity-90"
                    }`}
                  >
                    {mod.is_installed ? (
                      <>
                        <Trash2 className="h-4 w-4" />
                        <span>{"Uninstall Module"}</span>
                      </>
                    ) : (
                      <>
                        <Download className="h-4 w-4" />
                        <span>{"Install Module"}</span>
                      </>
                    )}
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
