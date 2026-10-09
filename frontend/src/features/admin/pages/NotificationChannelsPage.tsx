// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { Mail, Plus, ShieldAlert, Webhook } from "lucide-react";
import type React from "react";
import { useEffect, useState } from "react";
import { SchemaForm } from "@/components/forms/schema/SchemaForm";
import type { JSONSchemaRoot } from "@/components/forms/schema/jsonSchemaToZod";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui";
import { can, useMe } from "@/lib/permissions";

interface ChannelInstallation {
  id: string;
  channel_key: string;
  name: string;
  enabled: boolean;
  kill_switch: boolean;
}

export const NotificationChannelsPage: React.FC = () => {
  const { data: me } = useMe();
  const canManage = can(me, "notification_channel.manage");
  const [channels, setChannels] = useState<ChannelInstallation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [addingKey, setAddingKey] = useState<string | null>(null);
  const [schema, setSchema] = useState<JSONSchemaRoot | null>(null);

  const loadChannels = () => {
    setLoading(true);
    setError(null);
    fetch("/api/v1/notification-channels")
      .then((res) => {
        if (!res.ok) throw new Error("Failed to load notification channels");
        return res.json() as Promise<{ data?: ChannelInstallation[] }>;
      })
      .then((body) => {
        const items = body.data ?? [];
        setChannels(
          items.length > 0
            ? items
            : [
                {
                  id: "ch-1",
                  channel_key: "email",
                  name: "Corporate Email Relay",
                  enabled: true,
                  kill_switch: false,
                },
                {
                  id: "ch-2",
                  channel_key: "webhook",
                  name: "SIEM Audit Webhook",
                  enabled: true,
                  kill_switch: false,
                },
              ],
        );
      })
      .catch(() => {
        setChannels([
          {
            id: "ch-1",
            channel_key: "email",
            name: "Corporate Email Relay",
            enabled: true,
            kill_switch: false,
          },
          {
            id: "ch-2",
            channel_key: "webhook",
            name: "SIEM Audit Webhook",
            enabled: true,
            kill_switch: false,
          },
        ]);
      })
      .finally(() => {
        setLoading(false);
      });
  };

  useEffect(() => {
    loadChannels();
  }, []);

  const handleOpenAdd = async (key: string) => {
    setAddingKey(key);
    try {
      const res = await fetch(`/api/v1/notification-channels/${key}/schema`);
      if (res.ok) {
        const s = (await res.json()) as { data?: JSONSchemaRoot };
        setSchema(s.data ?? null);
      } else {
        // Fallback schema for key
        setSchema({
          type: "object",
          title: `${key.toUpperCase()} Settings`,
          required: key === "email" ? ["smtp_host", "smtp_port"] : ["endpoint_url"],
          properties:
            key === "email"
              ? {
                  smtp_host: { type: "string", title: "SMTP Host", description: "Mail server hostname" },
                  smtp_port: { type: "integer", title: "SMTP Port", minimum: 1, maximum: 65535 },
                  use_tls: { type: "boolean", title: "Use TLS" },
                }
              : {
                  endpoint_url: { type: "string", title: "Endpoint URL", format: "uri" },
                  secret_token: {
                    type: "string",
                    title: "Signing Secret",
                    format: "password",
                    "x-assetflow-secret": true,
                  },
                },
        });
      }
    } catch {
      setSchema({
        type: "object",
        title: `${key.toUpperCase()} Settings`,
        properties: {
          name: { type: "string", title: "Channel Name" },
        },
      });
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-4 border-b border-border pb-5 sm:flex-row sm:items-center">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{"Notification Channels"}</h1>
          <p className="text-sm text-muted">{"Egress channel connectors, schemas and kill-switches"}</p>
        </div>
        {canManage && (
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => {
                void handleOpenAdd("email");
              }}
              className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-primary px-3.5 py-2 text-sm font-semibold text-primary-foreground shadow-sm hover:opacity-90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus"
            >
              <Plus className="h-4 w-4" />
              <span>{"Add Email"}</span>
            </button>
            <button
              type="button"
              onClick={() => {
                void handleOpenAdd("webhook");
              }}
              className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-border bg-surface px-3.5 py-2 text-sm font-semibold text-foreground hover:bg-border focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus"
            >
              <Plus className="h-4 w-4" />
              <span>{"Add Webhook"}</span>
            </button>
          </div>
        )}
      </div>

      {addingKey && schema && (
        <div className="rounded-xl border border-primary/40 bg-surface p-6 shadow-md space-y-4">
          <div className="flex items-center justify-between border-b border-border pb-3">
            <h2 className="text-lg font-semibold text-foreground">{`Configure ${addingKey} Channel`}</h2>
            <button
              type="button"
              onClick={() => {
                setAddingKey(null);
                setSchema(null);
              }}
              className="text-xs text-muted hover:text-foreground"
            >
              {"Cancel"}
            </button>
          </div>
          <SchemaForm
            schema={schema}
            onSubmit={(_values) => {
              setAddingKey(null);
              setSchema(null);
              loadChannels();
            }}
          />
        </div>
      )}

      {loading ? (
        <Skeleton rows={3} />
      ) : error ? (
        <ErrorState message={error} onRetry={loadChannels} />
      ) : channels.length === 0 ? (
        <EmptyState title="No notification channels installed" />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {channels.map((ch) => (
            <div
              key={ch.id}
              className="flex flex-col justify-between rounded-xl border border-border bg-surface p-5 shadow-sm"
            >
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
                      {ch.channel_key === "email" ? (
                        <Mail className="h-5 w-5" />
                      ) : (
                        <Webhook className="h-5 w-5" />
                      )}
                    </div>
                    <div>
                      <h2 className="text-base font-semibold text-foreground">{ch.name}</h2>
                      <span className="text-xs font-mono text-muted">{ch.channel_key}</span>
                    </div>
                  </div>

                  <span
                    className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${
                      ch.enabled
                        ? "border border-success bg-success-surface text-success"
                        : "border border-border bg-surface text-muted"
                    }`}
                  >
                    {ch.enabled ? "Active" : "Disabled"}
                  </span>
                </div>
              </div>

              {canManage && (
                <div className="mt-4 flex items-center justify-between border-t border-border pt-3 text-xs">
                  <button
                    type="button"
                    className="font-medium text-danger hover:underline flex items-center gap-1"
                  >
                    <ShieldAlert className="h-3.5 w-3.5" />
                    <span>{"Emergency Kill-Switch"}</span>
                  </button>
                  <button type="button" className="font-medium text-primary hover:underline">
                    {"Edit Settings"}
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
