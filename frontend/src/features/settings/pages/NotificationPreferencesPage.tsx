// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { Lock } from "lucide-react";
import type React from "react";
import { useEffect, useState } from "react";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui";
import { ProblemError, apiFetch } from "@/lib/api";

// `GET/PUT /api/v1/me/notification-preferences`: every event type the member can receive by every
// installed channel. A locked cell (mandatory in-app notice) cannot be switched off.
interface PreferenceCell {
  channel_key: string;
  enabled: boolean;
  version: number;
  locked: boolean;
}

interface PreferenceEvent {
  event_type: string;
  channels: PreferenceCell[];
}

interface PreferenceMatrix {
  channels: string[];
  events: PreferenceEvent[];
}

interface PreferenceChange {
  event_type: string;
  channel_key: string;
  enabled: boolean;
  version?: number;
}

const PATH = "/me/notification-preferences";

function cellKey(eventType: string, channelKey: string): string {
  return `${eventType}|${channelKey}`;
}

export const NotificationPreferencesPage: React.FC = () => {
  const [matrix, setMatrix] = useState<PreferenceMatrix | null>(null);
  const [pending, setPending] = useState<Map<string, boolean>>(new Map());
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadPreferences = () => {
    setLoading(true);
    setLoadError(null);
    apiFetch<PreferenceMatrix>(PATH)
      .then((data) => {
        setMatrix(data);
        setPending(new Map());
      })
      .catch(() => {
        setLoadError("Failed to load notification preferences");
      })
      .finally(() => {
        setLoading(false);
      });
  };

  useEffect(() => {
    loadPreferences();
  }, []);

  const isEnabled = (event: PreferenceEvent, cell: PreferenceCell): boolean =>
    pending.get(cellKey(event.event_type, cell.channel_key)) ?? cell.enabled;

  const handleToggle = (event: PreferenceEvent, cell: PreferenceCell) => {
    if (cell.locked) return;
    const key = cellKey(event.event_type, cell.channel_key);
    setPending((prev) => {
      const next = new Map(prev);
      const wanted = !isEnabled(event, cell);
      if (wanted === cell.enabled) next.delete(key);
      else next.set(key, wanted);
      return next;
    });
    setSaved(false);
  };

  const handleSave = async () => {
    if (matrix === null || pending.size === 0) return;
    const changes: PreferenceChange[] = [];
    for (const event of matrix.events) {
      for (const cell of event.channels) {
        const wanted = pending.get(cellKey(event.event_type, cell.channel_key));
        if (wanted === undefined) continue;
        // Version 0 means the cell was never changed; the API wants it omitted then.
        changes.push({
          event_type: event.event_type,
          channel_key: cell.channel_key,
          enabled: wanted,
          ...(cell.version > 0 ? { version: cell.version } : {}),
        });
      }
    }
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      const updated = await apiFetch<PreferenceMatrix>(PATH, { method: "PUT", body: { changes } });
      setMatrix(updated);
      setPending(new Map());
      setSaved(true);
    } catch (err: unknown) {
      setError(
        err instanceof ProblemError && err.detail ? err.detail : "Failed to save notification preferences",
      );
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <Skeleton rows={4} />;
  if (loadError || matrix === null) {
    return (
      <ErrorState
        message={loadError ?? "Failed to load notification preferences"}
        onRetry={loadPreferences}
      />
    );
  }

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

      {matrix.events.length === 0 ? (
        <EmptyState title="No notifications to configure" />
      ) : (
        <div className="rounded-xl border border-border bg-surface overflow-hidden shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-border bg-border/20 text-xs font-semibold uppercase text-muted">
                <tr>
                  <th className="p-4">{"Notification Event"}</th>
                  {matrix.channels.map((channel) => (
                    <th key={channel} className="p-4 text-center">
                      {channel}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {matrix.events.map((event) => (
                  <tr key={event.event_type} className="hover:bg-border/20">
                    <td className="p-4 font-mono text-xs text-foreground">{event.event_type}</td>
                    {matrix.channels.map((channel) => {
                      const cell = event.channels.find((c) => c.channel_key === channel);
                      if (cell === undefined) return <td key={channel} className="p-4" />;
                      return (
                        <td key={channel} className="p-4 text-center">
                          <div className="inline-flex items-center justify-center gap-1">
                            <input
                              type="checkbox"
                              aria-label={`${event.event_type} by ${channel}`}
                              checked={isEnabled(event, cell)}
                              disabled={cell.locked}
                              onChange={() => {
                                handleToggle(event, cell);
                              }}
                              className="h-4 w-4 cursor-pointer rounded border-border text-primary disabled:cursor-not-allowed disabled:opacity-60"
                            />
                            {cell.locked && (
                              <span title="Mandatory notification">
                                <Lock className="h-3 w-3 text-muted" aria-hidden="true" />
                              </span>
                            )}
                          </div>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="pt-2">
        <button
          type="button"
          onClick={() => {
            void handleSave();
          }}
          disabled={saving || pending.size === 0}
          className="inline-flex min-h-11 items-center justify-center rounded-lg bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground shadow-sm hover:opacity-90 disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus"
        >
          {saving ? "Saving…" : "Save Preferences"}
        </button>
      </div>
    </div>
  );
};
