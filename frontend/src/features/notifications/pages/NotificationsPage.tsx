// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { CheckCheck, Filter } from "lucide-react";
import type React from "react";
import { useEffect, useState } from "react";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui";
import { formatRelativeTime, t } from "@/lib/i18n";
import { fetchNotifications, markAllRead, markRead, type NotificationItem } from "../api";

export const NotificationsPage: React.FC = () => {
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const loadNotifications = () => {
    setLoading(true);
    setError(null);
    fetchNotifications()
      .then(setNotifications)
      .catch(() => {
        setError("Failed to load notifications");
      })
      .finally(() => {
        setLoading(false);
      });
  };

  useEffect(() => {
    loadNotifications();
  }, []);

  const handleMarkAllRead = async () => {
    setActionError(null);
    try {
      await markAllRead();
      setNotifications((prev) => prev.map((n) => ({ ...n, isRead: true })));
    } catch {
      setActionError("Could not mark the notifications as read");
    }
  };

  const handleMarkRead = async (id: string) => {
    setActionError(null);
    try {
      await markRead(id);
      setNotifications((prev) => prev.map((n) => (n.id === id ? { ...n, isRead: true } : n)));
    } catch {
      setActionError("Could not mark the notification as read");
    }
  };

  const filtered = unreadOnly ? notifications.filter((n) => !n.isRead) : notifications;

  return (
    <div className="space-y-6 max-w-4xl">
      <div className="flex flex-col justify-between gap-4 border-b border-border pb-5 sm:flex-row sm:items-center">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{t("nav.items.notifications")}</h1>
          <p className="text-sm text-muted">{"In-app activity alerts and updates"}</p>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => {
              setUnreadOnly(!unreadOnly);
            }}
            className={`inline-flex min-h-11 items-center gap-1.5 rounded-lg border px-3 text-xs font-semibold ${
              unreadOnly
                ? "border-primary bg-primary/10 text-primary"
                : "border-border bg-surface text-foreground"
            }`}
          >
            <Filter className="h-3.5 w-3.5" />
            <span>{"Unread Only"}</span>
          </button>

          <button
            type="button"
            onClick={() => {
              void handleMarkAllRead();
            }}
            className="inline-flex min-h-11 items-center gap-1.5 rounded-lg border border-border bg-surface px-3 text-xs font-semibold text-foreground hover:bg-border focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus"
          >
            <CheckCheck className="h-4 w-4 text-primary" />
            <span>{"Mark All Read"}</span>
          </button>
        </div>
      </div>

      {actionError && <ErrorState message={actionError} />}

      {loading ? (
        <Skeleton rows={4} />
      ) : error ? (
        <ErrorState message={error} onRetry={loadNotifications} />
      ) : filtered.length === 0 ? (
        <EmptyState title="No notifications" message="You are completely caught up." />
      ) : (
        <div className="divide-y divide-border rounded-xl border border-border bg-surface shadow-sm">
          {filtered.map((item) => (
            <div
              key={item.id}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  void handleMarkRead(item.id);
                }
              }}
              onClick={() => {
                void handleMarkRead(item.id);
              }}
              className={`flex items-start justify-between gap-4 p-4 transition-colors cursor-pointer hover:bg-border/30 focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus ${
                !item.isRead ? "bg-primary/5" : ""
              }`}
            >
              <div className="flex items-center gap-2">
                {!item.isRead && <span className="h-2 w-2 rounded-full bg-primary" />}
                <h2 className={`text-sm font-semibold ${!item.isRead ? "text-foreground" : "text-muted"}`}>
                  {item.title}
                </h2>
              </div>
              <span className="shrink-0 text-xs text-muted">{formatRelativeTime(item.createdAt)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
