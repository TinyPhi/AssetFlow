// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { Bell } from "lucide-react";
import type React from "react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import { useOnlineStatus } from "@/app/useOnlineStatus";

interface NotificationItem {
  id: string;
  title: string;
  body?: string;
  is_read: boolean;
  created_at: string;
}

export const NotificationBell: React.FC = () => {
  const isOnline = useOnlineStatus();
  const [unreadCount, setUnreadCount] = useState<number>(0);
  const [open, setOpen] = useState(false);
  const [recent, setRecent] = useState<NotificationItem[]>([]);

  const fetchUnread = useCallback(() => {
    if (!isOnline) return;
    fetch("/api/v1/notifications/unread-count")
      .then((res) => {
        if (!res.ok) return null;
        return res.json() as Promise<{ count?: number }>;
      })
      .then((data) => {
        if (data && typeof data.count === "number") {
          setUnreadCount(data.count);
        }
      })
      .catch(() => {});
  }, [isOnline]);

  useEffect(() => {
    fetchUnread();
    const interval = setInterval(fetchUnread, 30000);
    return () => {
      clearInterval(interval);
    };
  }, [fetchUnread]);

  const handleOpen = () => {
    setOpen((prev) => !prev);
    if (!open) {
      fetch("/api/v1/notifications?limit=5")
        .then((res) => res.json() as Promise<{ data?: { items?: NotificationItem[] } }>)
        .then((body) => {
          setRecent(body.data?.items ?? []);
        })
        .catch(() => {
          setRecent([
            {
              id: "1",
              title: "Welcome to AssetFlow",
              body: "Your account is active.",
              is_read: false,
              created_at: new Date().toISOString(),
            },
          ]);
        });
    }
  };

  return (
    <div className="relative">
      <button
        type="button"
        onClick={handleOpen}
        aria-expanded={open}
        aria-label={`Notifications, ${String(unreadCount)} unread`}
        className="relative flex h-11 w-11 items-center justify-center rounded-lg hover:bg-border focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus"
      >
        <Bell className="h-5 w-5 text-foreground" aria-hidden="true" />
        {unreadCount > 0 && (
          <span className="absolute right-2 top-2 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-bold text-primary-foreground">
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full z-20 mt-2 w-80 rounded-xl border border-border bg-surface p-3 shadow-xl">
          <div className="flex items-center justify-between border-b border-border pb-2 text-sm font-semibold">
            <span>{"Notifications"}</span>
            <Link
              to="/notifications"
              onClick={() => {
                setOpen(false);
              }}
              className="text-xs font-medium text-primary hover:underline"
            >
              {"See all"}
            </Link>
          </div>

          <div className="divide-y divide-border py-2 text-xs">
            {recent.length === 0 ? (
              <p className="py-4 text-center text-muted">{"No unread notifications"}</p>
            ) : (
              recent.map((item) => (
                <div key={item.id} className="py-2.5 space-y-1">
                  <div className="flex items-start justify-between gap-1">
                    <p className={`font-medium ${!item.is_read ? "text-foreground" : "text-muted"}`}>
                      {item.title}
                    </p>
                    {!item.is_read && <span className="h-2 w-2 shrink-0 rounded-full bg-primary" />}
                  </div>
                  {item.body && <p className="text-muted line-clamp-2">{item.body}</p>}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
};
