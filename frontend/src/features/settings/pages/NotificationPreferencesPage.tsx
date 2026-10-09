// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { Lock } from "lucide-react";
import type React from "react";
import { useEffect, useState } from "react";
import { ErrorState, Skeleton } from "@/components/ui";

interface EventPreference {
  event_type: string;
  in_app: boolean;
  email: boolean;
  webhook: boolean;
}

const DEFAULT_PREFERENCES: EventPreference[] = [
  { event_type: "Work Order Assigned", in_app: true, email: true, webhook: false },
  { event_type: "Work Order Dispatched", in_app: true, email: true, webhook: false },
  { event_type: "Asset Status Changed", in_app: true, email: false, webhook: false },
  { event_type: "Team Member Added", in_app: true, email: true, webhook: false },
];

export const NotificationPreferencesPage: React.FC = () => {
  const [preferences, setPreferences] = useState<EventPreference[]>(DEFAULT_PREFERENCES);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/v1/me/notification-preferences")
      .then((res) => {
        if (!res.ok) throw new Error("Failed to load notification preferences");
        return res.json() as Promise<{ data?: EventPreference[] }>;
      })
      .then((body) => {
        if (body.data && body.data.length > 0) {
          setPreferences(body.data);
        }
      })
      .catch(() => {})
      .finally(() => {
        setLoading(false);
      });
  }, []);

  const handleToggle = (index: number, channel: "email" | "webhook") => {
    setPreferences((prev) =>
      prev.map((item, idx) => {
        if (idx !== index) return item;
        return channel === "email" ? { ...item, email: !item.email } : { ...item, webhook: !item.webhook };
      }),
    );
  };

  const handleSave = async () => {
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      await fetch("/api/v1/me/notification-preferences", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ preferences }),
      });
      setSaved(true);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <Skeleton rows={4} />;

  return (
    <div className="space-y-6 max-w-3xl">
      <div className="border-b border-border pb-5">
        <h1 className="text-2xl font-bold tracking-tight">{"Notification Preferences"}</h1>
        <p className="text-sm text-muted">{"Choose how you receive notifications across channels"}</p>
      </div>

      {error && <ErrorState message={error} />}
      {saved && (
        <div className="rounded-lg border border-success bg-success-surface p-3 text-sm text-success">
          {"Notification preferences updated successfully."}
        </div>
      )}

      <div className="rounded-xl border border-border bg-surface overflow-hidden shadow-sm">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-border bg-border/20 text-xs font-semibold uppercase text-muted">
              <tr>
                <th className="p-4">{"Notification Event"}</th>
                <th className="p-4 text-center">{"In-App"}</th>
                <th className="p-4 text-center">{"Email"}</th>
                <th className="p-4 text-center">{"Webhook"}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {preferences.map((pref, idx) => (
                <tr key={pref.event_type} className="hover:bg-border/20">
                  <td className="p-4 font-medium text-foreground">{pref.event_type}</td>
                  <td className="p-4 text-center">
                    <div className="inline-flex items-center justify-center gap-1">
                      <input
                        type="checkbox"
                        checked={pref.in_app}
                        disabled
                        className="h-4 w-4 rounded border-border text-primary opacity-60"
                      />
                      <span title="Mandatory in-app notification">
                        <Lock className="h-3 w-3 text-muted" aria-hidden="true" />
                      </span>
                    </div>
                  </td>
                  <td className="p-4 text-center">
                    <input
                      type="checkbox"
                      checked={pref.email}
                      onChange={() => {
                        handleToggle(idx, "email");
                      }}
                      className="h-4 w-4 rounded border-border text-primary focus:ring-primary cursor-pointer"
                    />
                  </td>
                  <td className="p-4 text-center">
                    <input
                      type="checkbox"
                      checked={pref.webhook}
                      onChange={() => {
                        handleToggle(idx, "webhook");
                      }}
                      className="h-4 w-4 rounded border-border text-primary focus:ring-primary cursor-pointer"
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="pt-2">
        <button
          type="button"
          onClick={() => {
            void handleSave();
          }}
          disabled={saving}
          className="inline-flex min-h-11 items-center justify-center rounded-lg bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground shadow-sm hover:opacity-90 disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus"
        >
          {saving ? "Saving…" : "Save Preferences"}
        </button>
      </div>
    </div>
  );
};
