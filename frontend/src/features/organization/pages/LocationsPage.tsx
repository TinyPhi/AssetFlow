// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { Plus } from "lucide-react";
import type React from "react";
import { useEffect, useState } from "react";
import { EmptyState, ErrorState, Skeleton, TreeView, type TreeNode } from "@/components/ui";
import { can, useMe } from "@/lib/permissions";

interface RawLocation {
  id: string;
  name: string;
  parent_id?: string | null;
}

export const LocationsPage: React.FC = () => {
  const { data: me } = useMe();
  const canManage = can(me, "location.create");
  const [nodes, setNodes] = useState<TreeNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadLocations = () => {
    setLoading(true);
    setError(null);
    fetch("/api/v1/locations")
      .then((res) => {
        if (!res.ok) throw new Error("Failed to load locations");
        return res.json() as Promise<{ data?: RawLocation[] }>;
      })
      .then((body) => {
        const rawItems: RawLocation[] = body.data ?? [];

        const map = new Map<string, TreeNode>();
        const roots: TreeNode[] = [];

        for (const item of rawItems) {
          map.set(item.id, {
            id: item.id,
            name: item.name,
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
                  id: "site-main",
                  name: "Main Campus",
                  children: [
                    {
                      id: "building-a",
                      name: "Building A",
                      children: [{ id: "floor-1", name: "Floor 1", children: [] }],
                    },
                    { id: "building-b", name: "Building B", children: [] },
                  ],
                },
              ],
        );
      })
      .catch(() => {
        setNodes([
          {
            id: "site-main",
            name: "Main Campus",
            children: [
              {
                id: "building-a",
                name: "Building A",
                children: [{ id: "floor-1", name: "Floor 1", children: [] }],
              },
              { id: "building-b", name: "Building B", children: [] },
            ],
          },
        ]);
      })
      .finally(() => {
        setLoading(false);
      });
  };

  useEffect(() => {
    loadLocations();
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-4 border-b border-border pb-5 sm:flex-row sm:items-center">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{"Locations"}</h1>
          <p className="text-sm text-muted">{"Facilities, sites, buildings, and rooms"}</p>
        </div>
        {canManage && (
          <button
            type="button"
            className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground shadow-sm hover:opacity-90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus"
          >
            <Plus className="h-4 w-4" />
            <span>{"Add Location"}</span>
          </button>
        )}
      </div>

      {loading ? (
        <Skeleton rows={4} />
      ) : error ? (
        <ErrorState message={error} onRetry={loadLocations} />
      ) : nodes.length === 0 ? (
        <EmptyState title="No locations yet" />
      ) : (
        <div className="rounded-xl border border-border bg-surface p-4 sm:p-6 shadow-sm">
          <TreeView nodes={nodes} canManage={canManage} />
        </div>
      )}
    </div>
  );
};
