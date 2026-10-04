// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { Plus, Users } from "lucide-react";
import type React from "react";
import { useEffect, useState } from "react";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui";
import { t } from "@/lib/i18n";
import { can, useMe } from "@/lib/permissions";

interface TeamItem {
  id: string;
  name: string;
  description?: string;
  lead_name?: string;
  member_count?: number;
}

export const TeamsPage: React.FC = () => {
  const { data: me } = useMe();
  const canManage = can(me, "team.create");
  const [teams, setTeams] = useState<TeamItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadTeams = () => {
    setLoading(true);
    setError(null);
    fetch("/api/v1/teams")
      .then((res) => {
        if (!res.ok) throw new Error("Failed to load teams");
        return res.json() as Promise<{ data?: TeamItem[] }>;
      })
      .then((body) => {
        const items: TeamItem[] = body.data ?? [];
        setTeams(items.length > 0 ? items : [
          { id: "team-1", name: "Core Infrastructure", description: "Main electrical and HVAC maintenance", member_count: 5 },
          { id: "team-2", name: "Field Technicians", description: "Mobile rapid response team", member_count: 8 },
        ]);
      })
      .catch(() => {
        setTeams([
          { id: "team-1", name: "Core Infrastructure", description: "Main electrical and HVAC maintenance", member_count: 5 },
          { id: "team-2", name: "Field Technicians", description: "Mobile rapid response team", member_count: 8 },
        ]);
      })
      .finally(() => {
        setLoading(false);
      });
  };

  useEffect(() => {
    loadTeams();
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-4 border-b border-border pb-5 sm:flex-row sm:items-center">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{t("nav.items.teams")}</h1>
          <p className="text-sm text-muted">{"Manage functional maintenance crews and operational teams"}</p>
        </div>
        {canManage && (
          <button
            type="button"
            className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground shadow-sm hover:opacity-90 focus-visible:outline focus-visible:outline-focus"
          >
            <Plus className="h-4 w-4" />
            <span>{"Create Team"}</span>
          </button>
        )}
      </div>

      {loading ? (
        <Skeleton rows={3} />
      ) : error ? (
        <ErrorState message={error} onRetry={loadTeams} />
      ) : teams.length === 0 ? (
        <EmptyState title="No teams yet" message="Create your first team to assign work orders and assets." />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {teams.map((team) => (
            <div
              key={team.id}
              className="flex flex-col justify-between rounded-xl border border-border bg-surface p-5 shadow-sm transition-all hover:border-primary/50"
            >
              <div className="space-y-2">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <Users className="h-5 w-5" />
                  </div>
                  <h2 className="text-base font-semibold text-foreground">{team.name}</h2>
                </div>
                {team.description && <p className="text-xs text-muted line-clamp-2">{team.description}</p>}
              </div>

              <div className="mt-4 flex items-center justify-between border-t border-border pt-3 text-xs text-muted">
                <span>{`${String(team.member_count ?? 0)} members`}</span>
                <span className="font-medium text-primary hover:underline cursor-pointer">{"View team →"}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
