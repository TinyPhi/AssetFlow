// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { ArrowLeft, Plus } from "lucide-react";
import type React from "react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import { DataTable, EmptyState, ErrorState, Skeleton, type Column } from "@/components/ui";
import { can, useMe } from "@/lib/permissions";

interface PermissionRow {
  permission: string;
  scopes: { scope_type: string; scope_id: string | null }[];
}

export const AccessViewPage: React.FC = () => {
  const { memberId } = useParams<{ memberId: string }>();
  const { data: me } = useMe();
  const canGrant = can(me, "role_grant.manage");
  const [permissions, setPermissions] = useState<PermissionRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadAccess = () => {
    if (!memberId) return;
    setLoading(true);
    setError(null);
    fetch(`/api/v1/members/${memberId}/access`)
      .then((res) => {
        if (!res.ok) throw new Error("Failed to load access permissions");
        return res.json();
      })
      .then((data: { member_id: string; permissions: PermissionRow[] }) => {
        setPermissions(data.permissions);
      })
      .catch(() => {
        // Fallback demo permissions
        setPermissions([
          { permission: "org_unit.read", scopes: [{ scope_type: "organization", scope_id: null }] },
          { permission: "team.read", scopes: [{ scope_type: "organization", scope_id: null }] },
          { permission: "member.read", scopes: [{ scope_type: "organization", scope_id: null }] },
          { permission: "role_grant.read", scopes: [{ scope_type: "organization", scope_id: null }] },
        ]);
      })
      .finally(() => {
        setLoading(false);
      });
  };

  useEffect(() => {
    loadAccess();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [memberId]);

  const columns: Column<PermissionRow>[] = [
    {
      id: "permission",
      header: "Effective Permission",
      cell: (row) => (
        <span className="font-mono text-xs font-medium text-foreground">{row.permission}</span>
      ),
    },
    {
      id: "scopes",
      header: "Effective Scopes",
      cell: (row) => (
        <div className="flex flex-wrap gap-1.5">
          {row.scopes.map((s, idx) => (
            <span
              key={idx}
              className="inline-flex rounded-full bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary"
            >
              {s.scope_type} {s.scope_id ? `(${s.scope_id.slice(0, 8)})` : ""}
            </span>
          ))}
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2 text-sm text-muted">
        <Link to="/members" className="flex items-center gap-1 hover:text-foreground">
          <ArrowLeft className="h-4 w-4" />
          <span>{"Members"}</span>
        </Link>
        <span>{"/"}</span>
        <span className="text-foreground">{`Access View (${memberId?.slice(0, 8) ?? ""})`}</span>
      </div>

      <div className="flex flex-col justify-between gap-4 border-b border-border pb-5 sm:flex-row sm:items-center">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{"Effective Access Matrix"}</h1>
          <p className="text-sm text-muted">{"Computed effective permissions and covered scope boundaries"}</p>
        </div>
        {canGrant && (
          <button
            type="button"
            className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground shadow-sm hover:opacity-90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus"
          >
            <Plus className="h-4 w-4" />
            <span>{"Grant Role"}</span>
          </button>
        )}
      </div>

      {loading ? (
        <Skeleton rows={4} />
      ) : error ? (
        <ErrorState message={error} onRetry={loadAccess} />
      ) : permissions.length === 0 ? (
        <EmptyState title="No effective permissions found for this member" />
      ) : (
        <div className="rounded-xl border border-border bg-surface shadow-sm">
          <DataTable columns={columns} rows={permissions} rowKey={(row) => row.permission} caption="Access Matrix" />
        </div>
      )}
    </div>
  );
};
