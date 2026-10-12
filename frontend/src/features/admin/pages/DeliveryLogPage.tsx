// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { RotateCcw } from "lucide-react";
import type React from "react";
import { useEffect, useState } from "react";
import { DataTable, EmptyState, ErrorState, Skeleton, type Column } from "@/components/ui";
import { ProblemError, apiFetch } from "@/lib/api";

// One row of `GET /api/v1/notification-channels/deliveries` (a page: `items` + `next_cursor`).
interface DeliveryLogItem {
  id: string;
  channel_key: string;
  target: string;
  status: string;
  attempts: number;
  error_code: string | null;
  created_at: string;
}

const DEAD_LETTERED = "dead_lettered";

export const DeliveryLogPage: React.FC = () => {
  const [logs, setLogs] = useState<DeliveryLogItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const loadLogs = () => {
    setLoading(true);
    setError(null);
    apiFetch<{ items: DeliveryLogItem[] }>("/notification-channels/deliveries")
      .then((page) => {
        setLogs(page.items);
      })
      .catch(() => {
        setError("Failed to load delivery logs");
      })
      .finally(() => {
        setLoading(false);
      });
  };

  useEffect(() => {
    loadLogs();
  }, []);

  const handleRequeue = async (id: string) => {
    setActionError(null);
    try {
      await apiFetch(`/notification-channels/deliveries/${id}/requeue`, { method: "POST" });
      loadLogs();
    } catch (err: unknown) {
      setActionError(
        err instanceof ProblemError && err.detail ? err.detail : "Failed to requeue the delivery",
      );
    }
  };

  const columns: Column<DeliveryLogItem>[] = [
    {
      id: "target",
      header: "Target",
      cell: (row) => (
        <div className="flex flex-col">
          <span className="font-mono text-xs font-semibold text-foreground">{row.target}</span>
          <span className="text-xs text-muted">{`Channel: ${row.channel_key}`}</span>
        </div>
      ),
    },
    {
      id: "status",
      header: "Status",
      cell: (row) => (
        <div className="flex flex-col gap-1">
          <span
            className={`inline-flex w-fit rounded-full px-2.5 py-0.5 text-xs font-medium ${
              row.status === "delivered"
                ? "border border-success bg-success-surface text-success"
                : row.status === DEAD_LETTERED
                  ? "border border-danger bg-danger-surface text-danger"
                  : "border border-border bg-surface text-muted"
            }`}
          >
            {`${row.status} (${String(row.attempts)}x)`}
          </span>
          {row.error_code && <span className="font-mono text-xs text-muted">{row.error_code}</span>}
        </div>
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
        row.status === DEAD_LETTERED ? (
          <button
            type="button"
            onClick={() => {
              void handleRequeue(row.id);
            }}
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

      {actionError && <ErrorState message={actionError} />}

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
