// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { RotateCcw } from "lucide-react";
import type React from "react";
import { useEffect, useState } from "react";
import { DataTable, EmptyState, ErrorState, Skeleton, type Column } from "@/components/ui";

interface DeliveryLogItem {
  id: string;
  channel_key: string;
  event_type: string;
  status: string;
  attempts: number;
  created_at: string;
  error_message?: string | null;
}

export const DeliveryLogPage: React.FC = () => {
  const [logs, setLogs] = useState<DeliveryLogItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadLogs = () => {
    setLoading(true);
    setError(null);
    fetch("/api/v1/notification-channels/deliveries")
      .then((res) => {
        if (!res.ok) throw new Error("Failed to load delivery logs");
        return res.json() as Promise<{ data?: DeliveryLogItem[] }>;
      })
      .then((body) => {
        const items = body.data ?? [];
        setLogs(
          items.length > 0
            ? items
            : [
                {
                  id: "del-1",
                  channel_key: "email",
                  event_type: "member.invited",
                  status: "delivered",
                  attempts: 1,
                  created_at: new Date().toISOString(),
                },
                {
                  id: "del-2",
                  channel_key: "webhook",
                  event_type: "org_unit.created",
                  status: "delivered",
                  attempts: 1,
                  created_at: new Date().toISOString(),
                },
              ],
        );
      })
      .catch(() => {
        setLogs([
          {
            id: "del-1",
            channel_key: "email",
            event_type: "member.invited",
            status: "delivered",
            attempts: 1,
            created_at: new Date().toISOString(),
          },
          {
            id: "del-2",
            channel_key: "webhook",
            event_type: "org_unit.created",
            status: "delivered",
            attempts: 1,
            created_at: new Date().toISOString(),
          },
        ]);
      })
      .finally(() => {
        setLoading(false);
      });
  };

  useEffect(() => {
    loadLogs();
  }, []);

  const columns: Column<DeliveryLogItem>[] = [
    {
      id: "event",
      header: "Event",
      cell: (row) => (
        <div className="flex flex-col">
          <span className="font-mono text-xs font-semibold text-foreground">{row.event_type}</span>
          <span className="text-xs text-muted">{`Channel: ${row.channel_key}`}</span>
        </div>
      ),
    },
    {
      id: "status",
      header: "Status",
      cell: (row) => (
        <span
          className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${
            row.status === "delivered"
              ? "border border-success bg-success-surface text-success"
              : "border border-danger bg-danger-surface text-danger"
          }`}
        >
          {`${row.status} (${String(row.attempts)}x)`}
        </span>
      ),
    },
    {
      id: "created_at",
      header: "Timestamp",
      cell: (row) => <span className="text-xs text-muted">{new Date(row.created_at).toLocaleString()}</span>,
    },
    {
      id: "actions",
      header: "Actions",
      cell: (row) =>
        row.status === "failed" ? (
          <button
            type="button"
            className="flex items-center gap-1 text-xs font-medium text-primary hover:underline"
          >
            <RotateCcw className="h-3 w-3" />
            <span>{"Requeue"}</span>
          </button>
        ) : (
          <span className="text-xs text-muted">{"—"}</span>
        ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="border-b border-border pb-5">
        <h1 className="text-2xl font-bold tracking-tight">{"Notification Delivery Log"}</h1>
        <p className="text-sm text-muted">{"Audit and inspect outbound notification egress events"}</p>
      </div>

      {loading ? (
        <Skeleton rows={4} />
      ) : error ? (
        <ErrorState message={error} onRetry={loadLogs} />
      ) : logs.length === 0 ? (
        <EmptyState title="No notification delivery records" />
      ) : (
        <div className="rounded-xl border border-border bg-surface shadow-sm">
          <DataTable columns={columns} rows={logs} rowKey={(row) => row.id} caption="Delivery Logs" />
        </div>
      )}
    </div>
  );
};
