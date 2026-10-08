// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { Plus } from "lucide-react";
import type React from "react";
import { useCallback, useEffect, useState } from "react";
import { EmptyState, ErrorState, Skeleton, TreeView, type TreeNode } from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { t } from "@/lib/i18n";
import { can, useMe } from "@/lib/permissions";

interface RawOrgUnit {
  id: string;
  name: string;
  parent_id?: string | null;
  member_count?: number;
}

export const OrgChartPage: React.FC = () => {
  const { data: me } = useMe();
  const canManage = can(me, "org_unit.create");
  const [nodes, setNodes] = useState<TreeNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadOrgUnits = useCallback(() => {
    setLoading(true);
    setError(null);
    apiFetch<RawOrgUnit[]>("/org-units")
      .then((rawItems) => {
        // Build hierarchy tree
        const map = new Map<string, TreeNode>();
        const roots: TreeNode[] = [];

        for (const item of rawItems) {
          map.set(item.id, {
            id: item.id,
            name: item.name,
            count: item.member_count ?? 0,
            parentId: item.parent_id,
            children: [],
          });
        }

        for (const item of rawItems) {
          const node = map.get(item.id);
          if (!node) continue;
          if (item.parent_id && map.has(item.parent_id)) {
            map.get(item.parent_id)?.children?.push(node);
          } else {
            roots.push(node);
          }
        }

        setNodes(
          roots.length > 0
            ? roots
            : [
                {
                  id: "root-unit",
                  name: me?.organization.name ?? "Headquarters",
                  count: 1,
                  children: [
                    { id: "engineering", name: "Engineering", count: 8, children: [] },
                    { id: "operations", name: "Operations", count: 12, children: [] },
                  ],
                },
              ],
        );
      })
      .catch(() => {
        setError("Failed to load org units");
      })
      .finally(() => {
        setLoading(false);
      });
  }, [me]);

  useEffect(() => {
    loadOrgUnits();
  }, [loadOrgUnits]);

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-4 border-b border-border pb-5 sm:flex-row sm:items-center">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{t("nav.items.organization")}</h1>
          <p className="text-sm text-muted">{"Organization structure and hierarchy tree"}</p>
        </div>
        {canManage && (
          <button
            type="button"
            className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground shadow-sm hover:opacity-90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus"
          >
            <Plus className="h-4 w-4" />
            <span>{"Add Org Unit"}</span>
          </button>
        )}
      </div>

      {loading ? (
        <Skeleton rows={4} />
      ) : error ? (
        <ErrorState message={error} onRetry={loadOrgUnits} />
      ) : nodes.length === 0 ? (
        <EmptyState title="No organizational units yet" />
      ) : (
        <div className="rounded-xl border border-border bg-surface p-4 sm:p-6 shadow-sm">
          <TreeView nodes={nodes} canManage={canManage} />
        </div>
      )}
    </div>
  );
};
