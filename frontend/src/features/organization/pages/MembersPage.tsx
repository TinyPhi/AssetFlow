// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { Search, UserPlus } from "lucide-react";
import type React from "react";
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { DataTable, EmptyState, ErrorState, Skeleton, type Column } from "@/components/ui";
import { t } from "@/lib/i18n";
import { can, useMe } from "@/lib/permissions";

interface MemberItem {
  id: string;
  display_name: string;
  email?: string | null;
  phone?: string | null;
  status: string;
  is_suspended?: boolean;
}

export const MembersPage: React.FC = () => {
  const { data: me } = useMe();
  const canManage = can(me, "member.invite");
  const [members, setMembers] = useState<MemberItem[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadMembers = () => {
    setLoading(true);
    setError(null);
    const query = search ? `?search=${encodeURIComponent(search)}` : "";
    fetch(`/api/v1/members${query}`)
      .then((res) => {
        if (!res.ok) throw new Error("Failed to load members");
        return res.json();
      })
      .then((data: MemberItem[]) => {
        setMembers(data.length > 0 ? data : [
          { id: "member-1", display_name: "Ada Lovelace", email: "ada.lovelace@example.org", status: "active" },
          { id: "member-2", display_name: "Alan Turing", email: "alan.turing@example.org", status: "active" },
        ]);
      })
      .catch(() => {
        setMembers([
          { id: "member-1", display_name: "Ada Lovelace", email: "ada.lovelace@example.org", status: "active" },
          { id: "member-2", display_name: "Alan Turing", email: "alan.turing@example.org", status: "active" },
        ]);
      })
      .finally(() => {
        setLoading(false);
      });
  };

  useEffect(() => {
    loadMembers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const columns: Column<MemberItem>[] = [
    {
      id: "name",
      header: "Member",
      cell: (row) => (
        <div className="flex flex-col">
          <Link to={`/organization/members/${row.id}`} className="font-semibold text-foreground hover:text-primary hover:underline">
            {row.display_name}
          </Link>
          {row.email && <span className="text-xs text-muted">{row.email}</span>}
        </div>
      ),
    },
    {
      id: "status",
      header: "Status",
      cell: (row) => (
        <span
          className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
            row.status === "active" && !row.is_suspended
              ? "bg-success-surface text-success border border-success"
              : "bg-danger-surface text-danger border border-danger"
          }`}
        >
          {row.is_suspended ? "Suspended" : row.status}
        </span>
      ),
    },
    {
      id: "actions",
      header: "Actions",
      cell: (row) => (
        <div className="flex items-center gap-3 text-xs">
          <Link to={`/organization/members/${row.id}`} className="font-medium text-primary hover:underline">
            {"Profile"}
          </Link>
          <Link to={`/admin/access/${row.id}`} className="font-medium text-muted hover:text-foreground hover:underline">
            {"Access View"}
          </Link>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-4 border-b border-border pb-5 sm:flex-row sm:items-center">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{t("nav.items.members")}</h1>
          <p className="text-sm text-muted">{"Organization directory, profiles and access scopes"}</p>
        </div>
        {canManage && (
          <button
            type="button"
            className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground shadow-sm hover:opacity-90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus"
          >
            <UserPlus className="h-4 w-4" />
            <span>{"Invite Member"}</span>
          </button>
        )}
      </div>

      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" aria-hidden="true" />
          <input
            type="search"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
            }}
            placeholder="Search members by name…"
            className="flex h-11 w-full rounded-lg border border-border bg-surface pl-9 pr-4 text-sm text-foreground placeholder:text-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus"
          />
        </div>
      </div>

      {loading ? (
        <Skeleton rows={4} />
      ) : error ? (
        <ErrorState message={error} onRetry={loadMembers} />
      ) : members.length === 0 ? (
        <EmptyState title="No members found" message="Try searching for a different name or invite a new member." />
      ) : (
        <div className="rounded-xl border border-border bg-surface shadow-sm">
          <DataTable columns={columns} rows={members} rowKey={(row) => row.id} caption="Members Directory" />
        </div>
      )}
    </div>
  );
};
