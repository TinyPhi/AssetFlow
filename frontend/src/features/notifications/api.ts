// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { apiFetch } from "@/lib/api";

/** One inbox row as `GET /api/v1/notifications` sends it. */
interface RawNotification {
  id: string;
  event_type: string;
  title_key: string;
  body: string | null;
  read_at: string | null;
  created_at: string;
}

/** What the bell and the inbox page show. */
export interface NotificationItem {
  id: string;
  title: string;
  isRead: boolean;
  createdAt: string;
}

function toItem(raw: RawNotification): NotificationItem {
  return {
    id: raw.id,
    title: raw.body !== null && raw.body !== "" ? raw.body : raw.event_type,
    isRead: raw.read_at !== null,
    createdAt: raw.created_at,
  };
}

export async function fetchNotifications(
  params: { limit?: number; unreadOnly?: boolean } = {},
): Promise<NotificationItem[]> {
  const query = new URLSearchParams();
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  if (params.unreadOnly === true) query.set("unread_only", "true");
  const suffix = query.size > 0 ? `?${query.toString()}` : "";
  const page = await apiFetch<{ items: RawNotification[] }>(`/notifications${suffix}`);
  return page.items.map(toItem);
}

export async function fetchUnreadCount(): Promise<number> {
  return (await apiFetch<{ unread: number }>("/notifications/unread-count")).unread;
}

export async function markRead(id: string): Promise<void> {
  await apiFetch(`/notifications/${id}/read`, { method: "POST" });
}

export async function markAllRead(): Promise<void> {
  await apiFetch("/notifications/read-all", { method: "POST" });
}
